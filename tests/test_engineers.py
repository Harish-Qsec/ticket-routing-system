import pytest
from pydantic import ValidationError

from app.exceptions import (
    DuplicateEngineerError,
    EngineerNotFoundError,
    NoAvailableEngineerError,
)
from app.models.enums import TicketCategory


def test_add_and_find_engineer(engineer_service, make_engineer_data):
    created = engineer_service.add_engineer(make_engineer_data())
    found = engineer_service.get_engineer("E-1")

    assert found.engineer_id == created.engineer_id == "E-1"
    assert found.is_available is True
    assert found.skills == {TicketCategory.NETWORK}



def test_find_missing_engineer_raises(engineer_service):
    with pytest.raises(EngineerNotFoundError):
        engineer_service.get_engineer("nope")


def test_duplicate_engineer_id_is_rejected(engineer_service, make_engineer_data):
    engineer_service.add_engineer(make_engineer_data("E-1", name="Original"))

    with pytest.raises(DuplicateEngineerError):
        engineer_service.add_engineer(make_engineer_data("E-1", name="Imposter"))

    assert len(engineer_service.list_engineers()) == 1
    assert engineer_service.get_engineer("E-1").name == "Original"


@pytest.mark.parametrize(
    "overrides",
    [
        {"engineer_id": ""},
        {"name": "   "},
        {"skills": set()},
        {"skills": {"COFFEE"}},
    ],
    ids=["empty-id", "blank-name", "no-skills", "unknown-skill"],
)
def test_invalid_engineer_data_is_rejected(make_engineer_data, overrides):
    with pytest.raises(ValidationError):
        make_engineer_data(**overrides)


def test_assign_engineer_matches_skill_and_marks_busy(
    engineer_service, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1"))

    engineer = engineer_service.assign_engineer(TicketCategory.NETWORK)

    assert engineer.engineer_id == "E-1"
    assert engineer.is_available is False


def test_assign_engineer_skips_wrong_skill(engineer_service, make_engineer_data):
    engineer_service.add_engineer(
        make_engineer_data("E-1", skills={TicketCategory.HARDWARE})
    )
    engineer_service.add_engineer(
        make_engineer_data("E-2", skills={TicketCategory.NETWORK})
    )

    assert engineer_service.assign_engineer(TicketCategory.NETWORK).engineer_id == "E-2"


def test_assign_engineer_skips_unavailable(engineer_service, make_engineer_data):
    engineer_service.add_engineer(make_engineer_data("E-1", is_available=False))
    engineer_service.add_engineer(make_engineer_data("E-2"))

    assert engineer_service.assign_engineer(TicketCategory.NETWORK).engineer_id == "E-2"


def test_assign_engineer_prefers_earliest_added(engineer_service, make_engineer_data):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    engineer_service.add_engineer(make_engineer_data("E-2"))

    assert engineer_service.assign_engineer(TicketCategory.NETWORK).engineer_id == "E-1"


def test_assign_raises_when_nobody_has_the_skill(engineer_service, make_engineer_data):
    engineer_service.add_engineer(make_engineer_data("E-1"))  # NETWORK only

    with pytest.raises(NoAvailableEngineerError):
        engineer_service.assign_engineer(TicketCategory.HARDWARE)


def test_assign_raises_when_everyone_is_busy(engineer_service, make_engineer_data):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    engineer_service.assign_engineer(TicketCategory.NETWORK)

    with pytest.raises(NoAvailableEngineerError):
        engineer_service.assign_engineer(TicketCategory.NETWORK)


def test_release_makes_engineer_assignable_again(engineer_service, make_engineer_data):
    engineer_service.add_engineer(make_engineer_data("E-1"))
    engineer_service.assign_engineer(TicketCategory.NETWORK)

    engineer_service.release_engineer("E-1")

    assert engineer_service.assign_engineer(TicketCategory.NETWORK).engineer_id == "E-1"


def test_release_missing_engineer_raises(engineer_service):
    with pytest.raises(EngineerNotFoundError):
        engineer_service.release_engineer("nope")



def test_name_length_boundary(make_engineer_data):
    make_engineer_data(name="n" * 100)  # accepted

    with pytest.raises(ValidationError):
        make_engineer_data(name="n" * 101)


def test_engineer_with_every_skill_can_be_assigned_for_each_category(
    engineer_service, make_engineer_data
):
    engineer_service.add_engineer(make_engineer_data("E-1", skills=set(TicketCategory)))

    for category in TicketCategory:
        assert engineer_service.assign_engineer(category).engineer_id == "E-1"
        engineer_service.release_engineer("E-1")



@pytest.mark.parametrize(
    "bad_id",
    ["E 1", "E/1", "E-1\nFORGED", "E-1;DROP", "\u00e9ngineer"],
    ids=["space", "slash", "newline", "semicolon", "non-ascii"],
)
def test_engineer_ids_with_unsafe_characters_are_rejected(make_engineer_data, bad_id):
    with pytest.raises(ValidationError):
        make_engineer_data(bad_id)