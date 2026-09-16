from gameswap import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nGameSwap closed. Any unfinished swap can be resumed on the next launch.")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"GameSwap: {error}")
        raise SystemExit(1)
