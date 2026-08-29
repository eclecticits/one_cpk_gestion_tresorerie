from app.utils.budget_code import cle_tri_code_budget


def test_tri_code_budget_compare_segments_numeriques():
    codes = ["II.2.13.4", "II.2.2", "II.2.1", "II.10", "I.9", "II.2"]

    assert sorted(codes, key=cle_tri_code_budget) == [
        "I.9",
        "II.2",
        "II.2.1",
        "II.2.2",
        "II.2.13.4",
        "II.10",
    ]


def test_tri_code_budget_ignore_espaces_points_et_casse():
    codes = [" ii..2.13.4 ", "II.2.2", ".II.2.1."]

    assert sorted(codes, key=cle_tri_code_budget) == [
        ".II.2.1.",
        "II.2.2",
        " ii..2.13.4 ",
    ]
