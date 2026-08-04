from time import perf_counter


if __name__ == "__main__":
    started_at = perf_counter()

    from jang_app.qt_app.main import main

    main(started_at)
