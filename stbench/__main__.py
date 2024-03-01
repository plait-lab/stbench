#!/usr/bin/env python3

from argparse import ArgumentParser


class Args:
    pass


def add_args(parser: ArgumentParser):
    pass


def main(args: Args):
    pass


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)
    main(parser.parse_args())  # type: ignore
