import pytest

from lys_bbb.conversion import parse_args


def test_fiji_display_is_opt_in() -> None:
    args = parse_args(["session"])
    assert args.write_fiji_display is False

    args = parse_args(["session", "--write-fiji-display"])
    assert args.write_fiji_display is True


def test_removed_negative_fiji_flag_is_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_args(["session", "--no-fiji-display"])
