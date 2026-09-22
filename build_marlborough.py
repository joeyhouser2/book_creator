"""Frank Taylor's The Wars of Marlborough (1921), both volumes, as facsimiles.

The Internet Archive's scans of the University of California copy, cleaned and
re-presented for print by book_creator.facsimile: python build_marlborough.py
"""

from __future__ import annotations

import sys

from book_creator import facsimile

COMMON = [
    "--title", "The Wars of Marlborough, 1702–1709",
    "--author", "Frank Taylor",
    "--editor", "G. Winifred Taylor",
    "--source", "at Oxford by Basil Blackwell in 1921",
    "--holder", "Joey Houser",
    "--credit", "The pages are from a scan of the University of California "
                "Libraries' copy, made by the Internet Archive.",
    "--cover-style", "band",
]

VOLUMES = {
    "1": ("Volume I", "Frank Taylor's history of Marlborough's wars, from the outbreak "
          "of the War of the Spanish Succession through Blenheim and Ramillies, "
          "reproduced page for page from the 1921 Blackwell edition, with its maps."),
    "2": ("Volume II", "Frank Taylor's history of Marlborough's wars, from Almanza and "
          "Oudenarde to the siege of Lille and the carnage of Malplaquet, reproduced "
          "page for page from the 1921 Blackwell edition, with its maps."),
}


def main(argv: list[str]) -> int:
    for v in argv or list(VOLUMES):
        subtitle, blurb = VOLUMES[v]
        facsimile.main([f"input/warsofmarlboroug0{v}tayl.pdf", *COMMON,
                        "--subtitle", subtitle, "--blurb", blurb])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
