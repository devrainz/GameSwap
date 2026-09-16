import threading
from pathlib import Path
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango
from config import load_config, normalize_library, save_config
from gameswap import VERSION, plan_move, plan_swap, run_queue
from state import STATE_FILE, acquire_lock, load_state, save_state
from steam import filter_games, scan_library
from verify import check_environment

APP_ID = "io.github.devrainz.GameSwap"


def label(text, style=None):
    widget = Gtk.Label(label=text, wrap=True, xalign=0)
    if style:
        widget.add_css_class(style)
    return widget


def button(text, callback, style=None):
    widget = Gtk.Button(label=text, halign=Gtk.Align.CENTER)
    if style:
        widget.add_css_class(style)
    widget.connect("clicked", callback)
    return widget


def padded_box(spacing=18, margin=24):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing,
                   margin_top=margin, margin_bottom=margin, margin_start=margin, margin_end=margin)


class GameSwapWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="GameSwap", default_width=940, default_height=720)
        self.set_size_request(420, 500)
        self.busy = False
        self.transferring = False
        self.recovery = None
        self.blocked = False
        self.selection = [None, None]
        self.mode = "dual"
        self.pause_event = threading.Event()
        self.progress_lock = threading.Lock()
        self.progress_data = {}
        self.progress_timer = None
        self.lock_handle = None
        self.inhibit_cookie = 0
        self.connect("close-request", self.close_requested)
        self.connect("destroy", self.destroyed)
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(shell)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="GameSwap", subtitle="Your games. The right drive."))
        menu = Gio.Menu()
        menu.append("Libraries", "app.libraries")
        menu.append("About GameSwap", "app.about")
        menu.append("Quit", "app.quit")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        shell.append(header)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        shell.append(self.stack)
        self.build_home()
        self.build_progress()
        self.build_result()
        try:
            self.lock_handle = acquire_lock()
            self.config = load_config()
            self.recovery = load_state()
            if Path(".truckswap_state.json").exists() and not self.recovery:
                raise RuntimeError("An old TruckSwap recovery record exists in this directory. Inspect that transfer before using GameSwap.")
        except Exception as error:
            self.config = {"main_library": None, "backup_library": None}
            self.blocked = True
            GLib.idle_add(self.show_error, "Cannot start safely", str(error))
        self.refresh_home()

    def page(self, name):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=800, tightening_threshold=620)
        content = padded_box()
        clamp.set_child(content)
        scroll.set_child(clamp)
        self.stack.add_named(scroll, name)
        return content

    def build_home(self):
        page = self.page("home")
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_bottom=8)
        logo_path = Path(__file__).parent / "assets/logo.png"
        icon = Gtk.Image.new_from_file(str(logo_path))
        icon.set_pixel_size(72)
        hero.append(icon)
        heading = label("Make room for what’s next", "title-1")
        heading.set_xalign(0.5)
        hero.append(heading)
        self.hero_subtitle = label("Choose one game from each Steam library, then swap their places.", "dim-label")
        self.hero_subtitle.set_xalign(0.5)
        hero.append(self.hero_subtitle)
        page.append(hero)

        mode_group = Adw.PreferencesGroup(title="Transfer mode")
        mode_row = Adw.ActionRow(title="How should GameSwap move your games?")
        mode_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        self.dual_mode_button = Gtk.ToggleButton(label="Dual swap")
        self.single_mode_button = Gtk.ToggleButton(label="Single move")
        self.single_mode_button.set_group(self.dual_mode_button)
        self.dual_mode_button.set_active(True)
        self.dual_mode_button.connect("toggled", lambda widget: self.set_mode("dual") if widget.get_active() else None)
        self.single_mode_button.connect("toggled", lambda widget: self.set_mode("single") if widget.get_active() else None)
        mode_buttons.append(self.dual_mode_button)
        mode_buttons.append(self.single_mode_button)
        mode_row.add_suffix(mode_buttons)
        mode_group.add(mode_row)
        page.append(mode_group)
        self.recovery_group = Adw.PreferencesGroup(title="Unfinished swap")
        self.recovery_row = Adw.ActionRow(title="Your last operation can be resumed")
        self.resume_button = button("Resume", lambda *_: self.resume(), "suggested-action")
        self.resume_button.set_valign(Gtk.Align.CENTER)
        self.recovery_row.add_suffix(self.resume_button)
        self.recovery_group.add(self.recovery_row)
        page.append(self.recovery_group)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           column_spacing=18, row_spacing=18, min_children_per_line=1, max_children_per_line=2)
        self.cards = []
        for index, name in enumerate(("Main library", "Secondary library")):
            card = padded_box(margin=20)
            card.add_css_class("card")
            card.append(label(name.upper(), "caption-heading"))
            game_name = label("Choose a game", "title-2")
            game_name.set_vexpand(True)
            card.append(game_name)
            path = label("Choose a Steam library in Libraries", "dim-label")
            path.set_lines(2)
            path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            card.append(path)
            choose = button("Browse games", lambda _, i=index: self.browse(i))
            choose.set_halign(Gtk.Align.FILL)
            card.append(choose)
            flow.insert(card, -1)
            self.cards.append((game_name, path, choose))
        page.append(flow)
        self.setup_button = button("Choose Steam libraries", lambda *_: self.preferences(), "suggested-action")
        page.append(self.setup_button)
        self.review_button = button("Review swap", lambda *_: self.review(), "suggested-action")
        self.review_button.add_css_class("pill")
        page.append(self.review_button)
        self.home_status = label("No downloads. Files are verified before the originals are removed.", "dim-label")
        self.home_status.set_xalign(0.5)
        page.append(self.home_status)
        self.spinner = Gtk.Spinner(halign=Gtk.Align.CENTER)
        page.append(self.spinner)

    def build_progress(self):
        page = self.page("progress")
        page.append(label("Moving your games", "title-1"))
        self.transfer_title = label("Preparing…", "title-2")
        page.append(self.transfer_title)
        group = Adw.PreferencesGroup()
        self.stage_row = Adw.ActionRow(title="Preparing transfer")
        group.add(self.stage_row)
        page.append(group)
        self.progress_bar = Gtk.ProgressBar(show_text=True, text="Preparing…")
        page.append(self.progress_bar)
        self.speed_label = label("Speed —    ·    Time remaining —", "dim-label")
        page.append(self.speed_label)
        page.append(label("Keep Steam and both games closed. Leave both drives connected.\n"
                          "Verification may take several minutes and reads every file."))
        self.pause_button = button("Pause safely", lambda *_: self.request_pause())
        page.append(self.pause_button)
        self.pause_note = label("You can resume from the saved checkpoint.", "dim-label")
        self.pause_note.set_xalign(0.5)
        page.append(self.pause_note)

    def build_result(self):
        page = self.page("result")
        self.result_icon = Gtk.Image(icon_name="emblem-ok-symbolic", pixel_size=64, margin_top=32)
        page.append(self.result_icon)
        self.result_title = label("Swap complete", "title-1")
        self.result_title.set_xalign(0.5)
        page.append(self.result_title)
        self.result_body = label("")
        self.result_body.set_selectable(True)
        page.append(self.result_body)
        page.append(button("Back to games", lambda *_: self.return_home(), "suggested-action"))

    def refresh_home(self):
        configured = all(self.config.values())
        available = not self.busy and not self.blocked and self.recovery is None
        for index, (heading, path, choose) in enumerate(self.cards):
            key = "main_library" if index == 0 else "backup_library"
            game = self.selection[index]
            heading.set_label(game["name"] if game else "Choose a game")
            path.set_label(self.config[key] or "Not configured")
            path.set_tooltip_text(self.config[key] or "Choose a library")
            choose.set_sensitive(available and configured)
        self.dual_mode_button.set_sensitive(available)
        self.single_mode_button.set_sensitive(available)
        self.setup_button.set_visible(not configured)
        self.setup_button.set_sensitive(available)
        selected_count = sum(game is not None for game in self.selection)
        ready = all(self.selection) if self.mode == "dual" else selected_count == 1
        self.review_button.set_sensitive(available and ready)
        self.review_button.set_label("Review swap" if self.mode == "dual" else "Review move")
        self.hero_subtitle.set_label(
            "Choose one game from each Steam library, then swap their places."
            if self.mode == "dual" else
            "Choose one game from either library. It will be moved to the other library."
        )
        self.recovery_group.set_visible(self.recovery is not None)
        self.resume_button.set_sensitive(not self.busy and not self.blocked)
        if self.recovery:
            stage = (self.recovery.get("transfer") or {}).get("stage", "waiting")
            total = len(self.recovery.get("jobs") or [])
            self.recovery_row.set_subtitle(f'{self.recovery["index"]}/{total} transfers completed · {stage}')
        self.spinner.set_spinning(self.busy)
        self.spinner.set_visible(self.busy)

    def set_mode(self, mode):
        if mode == self.mode:
            return
        if self.busy or self.transferring or self.recovery:
            return
        self.mode = mode
        self.selection = [None, None]
        self.home_status.set_label(
            "Choose one game from each library to swap them."
            if mode == "dual" else
            "Choose one game from either library to move it to the other."
        )
        self.refresh_home()

    def show_error(self, heading, message):
        dialog = Adw.MessageDialog(transient_for=self, heading=heading, body=str(message))
        dialog.add_response("close", "Close")
        dialog.set_close_response("close")
        dialog.present()
        return GLib.SOURCE_REMOVE

    def background(self, operation, callback):
        if self.busy:
            return
        self.busy = True
        self.refresh_home()

        def finished(value, error):
            self.busy = False
            self.refresh_home()
            if error:
                self.show_error("Could not continue", error)
            else:
                callback(value)
            return GLib.SOURCE_REMOVE

        def worker():
            try:
                value = operation()
            except Exception as error:
                GLib.idle_add(finished, None, str(error))
            else:
                GLib.idle_add(finished, value, None)

        threading.Thread(target=worker, name="gameswap-work", daemon=False).start()

    def preferences(self):
        if self.busy or self.blocked or self.recovery:
            self.show_error("Libraries are locked", "Finish or resume the current operation before changing libraries.")
            return
        window = Adw.PreferencesWindow(transient_for=self, modal=True, title="Steam Libraries",
                                       default_width=620, default_height=400)
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Library locations", description="Choose the library folder or its steamapps folder.")
        entries = []
        for key, name in (("main_library", "Main library"), ("backup_library", "Secondary library")):
            row = Adw.EntryRow(title=name)
            row.set_text(self.config[key] or "")
            browse = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text=f"Browse for {name.lower()}")
            browse.add_css_class("flat")
            browse.connect("clicked", lambda _, entry=row: self.choose_folder(window, entry))
            row.add_suffix(browse)
            group.add(row)
            entries.append(row)
        page.add(group)
        actions = Adw.PreferencesGroup()
        save_row = Adw.ActionRow()

        def save(*_):
            try:
                main, secondary = [normalize_library(entry.get_text().strip()) for entry in entries]
                if main == secondary or main in secondary.parents or secondary in main.parents:
                    raise ValueError("Choose two separate, non-nested libraries.")
                config = {"main_library": str(main), "backup_library": str(secondary)}
                save_config(config)
            except Exception as error:
                self.show_error("Cannot save libraries", str(error))
                return
            self.config = config
            self.selection = [None, None]
            window.close()
            self.refresh_home()

        save_button = button("Save libraries", save, "suggested-action")
        save_button.set_valign(Gtk.Align.CENTER)
        save_row.add_suffix(save_button)
        actions.add(save_row)
        page.add(actions)
        window.add(page)
        window.present()

    def choose_folder(self, parent, entry):
        chooser = Gtk.FileChooserNative(title="Select Steam library", transient_for=parent,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER,
                                        accept_label="Select", cancel_label="Cancel")
        path = entry.get_text().strip()
        if path and Path(path).expanduser().is_dir():
            chooser.set_current_folder(Gio.File.new_for_path(str(Path(path).expanduser())))

        def response(dialog, result):
            if result == Gtk.ResponseType.ACCEPT:
                selected = dialog.get_file()
                if selected and selected.get_path():
                    entry.set_text(selected.get_path())
            dialog.destroy()

        chooser.connect("response", response)
        chooser.show()

    def browse(self, index):
        key = "main_library" if index == 0 else "backup_library"
        self.home_status.set_label("Reading installed Steam games…")
        self.background(lambda: scan_library(self.config[key]), lambda result: self.show_browser(index, result))

    def show_browser(self, index, result):
        games, warnings = result
        self.home_status.set_label("Choose one game from each library to continue." if self.mode == "dual" else "Choose one game from either library to continue.")
        window = Adw.Window(transient_for=self, modal=True, title=f"Choose game {index + 1}",
                            default_width=660, default_height=580)
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Main library" if index == 0 else "Secondary library",
                                              subtitle=f"{len(games)} installed games"))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh games")
        refresh.connect("clicked", lambda *_: (window.close(), self.browse(index)))
        header.pack_start(refresh)
        shell.append(header)
        search = Gtk.SearchEntry(placeholder_text="Search by game name or AppID", margin_top=12,
                                 margin_bottom=12, margin_start=18, margin_end=18)
        shell.append(search)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                   margin_start=18, margin_end=18, margin_bottom=18)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        empty = Adw.StatusPage(title="No games found", description="Try another search or refresh this library.",
                              icon_name="system-search-symbolic")
        listing.set_placeholder(empty)
        rows = []
        for game in games:
            row = Adw.ActionRow(title=game["name"], subtitle=f'Steam AppID {game["appid"]}',
                                activatable=True, title_lines=2, subtitle_lines=1)
            row.set_use_markup(False)
            row.add_prefix(Gtk.Image(icon_name="applications-games-symbolic"))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            row.game = game
            row.connect("activated", lambda _, selected=game: self.select_game(index, selected, window))
            listing.append(row)
            rows.append(row)
        listing.set_filter_func(lambda row: bool(filter_games([row.game], search.get_text())))
        search.connect("search-changed", lambda *_: listing.invalidate_filter())

        def pick_first(*_):
            matches = filter_games(games, search.get_text())
            if matches:
                self.select_game(index, matches[0], window)

        search.connect("activate", pick_first)
        scroll.set_child(listing)
        shell.append(scroll)
        if warnings:
            details = button(f"{len(warnings)} manifests skipped · View details",
                             lambda *_: self.show_error("Skipped installations", "\n".join(warnings)))
            details.set_margin_bottom(12)
            shell.append(details)
        window.set_content(shell)
        window.present()
        search.grab_focus()

    def select_game(self, index, game, window):
        if self.mode == "single":
            self.selection = [None, None]
        self.selection[index] = game
        window.close()
        self.refresh_home()

    def review(self):
        self.home_status.set_label("Checking files, destinations, and available space…")
        first, second = self.selection
        if self.mode == "dual":
            self.background(lambda: ("dual", plan_swap(first, second)), self.show_review)
            return
        game = first or second
        destination = Path(self.config["backup_library"] if first else self.config["main_library"])
        self.background(lambda: ("single", plan_move(game, destination)), self.show_review)

    def show_review(self, result):
        mode, jobs = result
        text = "\n\n".join(f'{index}. {job["name"]}\nFrom: {job["library"]}\nTo: {job["destination"]}'
                            for index, job in enumerate(jobs, 1))
        if mode == "dual":
            text += "\n\nClose Steam and both games before continuing. Keep both drives connected."
            heading, action, response_id = "Ready to swap?", "Start swap", "start"
        else:
            text += "\n\nClose Steam and the selected game before continuing. Keep both drives connected."
            heading, action, response_id = "Ready to move?", "Start move", "start"
        dialog = Adw.MessageDialog(transient_for=self, heading=heading, body=text)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response(response_id, action)
        dialog.set_response_appearance(response_id, Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        journal = {"version": 1, "mode": mode, "jobs": jobs, "index": 0, "transfer": None}
        dialog.connect("response", lambda _, response: self.start_transfer(journal, fresh=True)
                       if response == response_id else None)
        dialog.present()

    def resume(self):
        try:
            journal = load_state()
            if journal is None:
                raise RuntimeError("The recovery record is no longer present.")
        except Exception as error:
            self.show_error("Cannot resume", str(error))
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="Resume unfinished swap?",
                                  body="Close Steam and both games, then reconnect the original drives.\n\n" +
                                  "\n".join(f'{job["name"]} → {job["destination"]}' for job in journal["jobs"]))
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("resume", "Resume")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("resume", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", lambda _, response: self.start_transfer(journal) if response == "resume" else None)
        dialog.present()

    def start_transfer(self, journal, fresh=False):
        if self.busy:
            return
        self.pause_event.clear()
        self.transferring = True
        self.pause_button.set_sensitive(True)
        self.pause_note.set_label("You can resume from the saved checkpoint.")
        self.progress_data = {"game": "Preparing…", "stage": "Checking Steam…", "percent": 0, "speed": "—", "eta": "—"}
        self.stack.set_visible_child_name("progress")
        self.progress_timer = GLib.timeout_add(150, self.draw_progress)
        self.inhibit_cookie = self.get_application().inhibit(self, Gtk.ApplicationInhibitFlags.SUSPEND,
                                                            "Moving and verifying Steam game files")

        def update(**values):
            if self.pause_event.is_set():
                raise RuntimeError("Pause requested. Files and recovery information were kept.")
            with self.progress_lock:
                self.progress_data.update(values)

        def operate():
            check_environment()
            if fresh:
                if load_state() is not None:
                    raise RuntimeError("An unfinished transfer already exists. Resume it first.")
                save_state(journal)
            return run_queue(journal,
                             on_game=lambda name, index, total: update(game=f"{index}/{total} · {name}"),
                             on_stage=lambda stage: update(stage=stage, percent=0, speed="—", eta="—"),
                             on_progress=lambda percent, speed, eta: update(percent=percent, speed=speed, eta=eta),
                             on_reset=lambda: None, should_pause=self.pause_event.is_set)

        def work():
            try:
                result = operate()
            except Exception as error:
                result = (False, str(error))
            return result

        self.background(work, self.transfer_finished)

    def draw_progress(self):
        with self.progress_lock:
            data = dict(self.progress_data)
        self.transfer_title.set_label(data.get("game", "Preparing…"))
        self.stage_row.set_title(data.get("stage", "Preparing…"))
        percent = max(0, min(100, data.get("percent", 0)))
        self.progress_bar.set_fraction(percent / 100)
        self.progress_bar.set_text(f"{percent}% of current stage")
        self.speed_label.set_label(f'Speed {data.get("speed", "—")}    ·    Time remaining {data.get("eta", "—")}')
        return GLib.SOURCE_CONTINUE

    def request_pause(self):
        self.pause_event.set()
        self.pause_button.set_sensitive(False)
        self.pause_note.set_label("Pausing at the next checkpoint. Finishing the current file may take a moment…")

    def transfer_finished(self, result):
        self.transferring = False
        if self.progress_timer:
            GLib.source_remove(self.progress_timer)
            self.progress_timer = None
        if self.inhibit_cookie:
            self.get_application().uninhibit(self.inhibit_cookie)
            self.inhibit_cookie = 0
        success, message = result
        try:
            self.recovery = load_state()
        except Exception as error:
            self.blocked = True
            message += f"\n\nCannot read recovery data: {error}"
        self.selection = [None, None]
        self.result_title.set_label("Transfer complete" if success else "Transfer paused" if self.recovery else "Transfer not started")
        self.result_icon.set_from_icon_name("emblem-ok-symbolic" if success else "dialog-warning-symbolic")
        self.result_body.set_label(message + (f"\n\nRecovery record: {STATE_FILE}" if self.recovery else ""))
        self.stack.set_visible_child_name("result")
        self.refresh_home()

    def return_home(self):
        self.stack.set_visible_child_name("home")
        self.refresh_home()

    def close_requested(self, *_):
        if self.transferring:
            self.request_pause()
            return True
        if self.busy:
            self.show_error("Still checking files", "Wait for the current check to finish before closing.")
            return True
        return False

    def destroyed(self, *_):
        if self.lock_handle:
            self.lock_handle.close()
            self.lock_handle = None


class GameSwapApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        for name, handler in (("libraries", lambda *_: self.get_active_window().preferences()),
                              ("about", self.about), ("quit", lambda *_: self.get_active_window().close())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])
        self.set_accels_for_action("app.libraries", ["<Primary>comma"])

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            window = GameSwapWindow(self)
        window.present()

    def about(self, *_):
        window = Adw.AboutWindow(transient_for=self.get_active_window(), modal=True,
                                 application_name="GameSwap", application_icon=APP_ID,
                                 version=VERSION, developer_name="Rainz",
                                 website="https://github.com/devrainz/GameSwap",
                                 issue_url="https://github.com/devrainz/GameSwap/issues",
                                 license_type=Gtk.License.MIT_X11)
        window.present()


def launch():
    if Adw.get_major_version() == 1 and Adw.get_minor_version() < 2:
        raise RuntimeError("GameSwap requires libadwaita 1.2 or newer.")
    return GameSwapApplication().run(["gameswap"])
