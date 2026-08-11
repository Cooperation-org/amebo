"""Every skill file in the core catalog is readable and complete.

A skill whose frontmatter cannot be read used to vanish from the catalog with
nothing on screen to say so: three skills were invisible for weeks because a
description contained a colon. Files are read tolerantly now, and this test
keeps the catalog honest either way.
"""

from __future__ import annotations

from src.services.skill_files import core_skills_dir, read_skills, split_frontmatter


def _core():
    return read_skills([core_skills_dir()])


def test_every_skill_has_a_name_and_description():
    for skill in _core():
        assert skill["name"], skill["path"]
        assert skill["description"], f"no description: {skill['path']}"
        assert skill["body"], f"no body: {skill['path']}"


def test_a_dashboard_skill_carries_its_button_and_its_ask():
    surfaced = [s for s in _core() if s["button"]]
    assert surfaced, "no skill offers a button"
    for skill in surfaced:
        assert skill["ask"], f"button without an ask: {skill['path']}"
        assert skill["audience"], f"button without an audience: {skill['path']}"
        assert skill["order"] != 999, f"button without an order: {skill['path']}"


def test_the_founder_run_is_in_one_order():
    orders = [s["order"] for s in _core() if s["audience"] == "founder" and s["button"]]
    assert len(orders) == len(set(orders)), "two founder skills claim the same place"


def test_frontmatter_survives_a_colon_yaml_would_reject():
    meta, body = split_frontmatter(
        "---\nname: x\ndescription: Coach them: what to ask\n---\n\nbody text\n"
    )
    assert meta["name"] == "x"
    assert meta["description"] == "Coach them: what to ask"
    assert body == "body text"
