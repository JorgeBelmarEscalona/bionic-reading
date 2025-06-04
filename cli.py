import argparse
import logging
from pathlib import Path
from queue import Queue
import Bionic


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate bionic EPUBs without GUI")
    parser.add_argument("files", nargs="+", help="EPUB files to process")
    parser.add_argument("-d", "--dest", required=True, help="Destination folder")
    args = parser.parse_args()

    logging.basicConfig(filename="bionic.log", level=logging.INFO, format="%(asctime)s - %(message)s")
    Bionic.ui_queue = Queue()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)

    for file in args.files:
        Bionic.generate_epub(Path(file), dest)
        while not Bionic.ui_queue.empty():
            event = Bionic.ui_queue.get()
            if event[0] == "log":
                print(event[1])


if __name__ == "__main__":
    main()
