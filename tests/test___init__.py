import pytest


@pytest.mark.parametrize("dose_type", ["DRY_HERB", "EDIBLE"])
def test_status(time_machine, dose_type):
    import doser

    dose_type: doser.IngestionMethod = getattr(doser, dose_type)
    dose = doser.Dose.new("potato", dose_type)
    time_machine.move_to(dose.processing_time.start)
    assert dose.status == doser.DoseStatus.processing
    time_machine.move_to(dose.active_time.start)
    assert dose.status == doser.DoseStatus.active
    time_machine.move_to(dose.active_time.end)
    assert dose.status == doser.DoseStatus.expired
