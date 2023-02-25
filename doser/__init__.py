import threading
import time
from enum import Enum
from functools import partial, wraps
from typing import NamedTuple

import flet
from pendulum import DateTime, Duration, duration, now, Period
from flet import (
    Column,
    ControlEvent,
    DataRow,
    IconButton,
    icons,
    Markdown,
    Radio,
    RadioGroup,
    Row,
    Text,
    TextField,
    UserControl,
    VerticalDivider,
)


class DoseStatus(Enum):
    processing = "PROCESSING"
    active = "ACTIVE"
    expired = "EXPIRED"


class IngestionMethod(NamedTuple):
    name: str
    onset: Duration
    duration: Duration


DRY_HERB = IngestionMethod("Dry Herb", Duration(minutes=15), Duration(hours=2))
EDIBLE = IngestionMethod("Edible", Duration(hours=2), Duration(hours=6))
FAKE_TEST_INGEST = IngestionMethod("TEST", Duration(seconds=15), Duration(seconds=15))


class Dose(NamedTuple):
    strain: str
    method: IngestionMethod
    ingested: DateTime
    processing_time: Period
    active_time: Period

    @classmethod
    def new(cls, strain: str, method: IngestionMethod, ingested: DateTime = None):
        kwargs = {"strain": strain, "method": method}
        kwargs["ingested"] = ingested = ingested or now("utc")
        kwargs["processing_time"] = proc_time = Period(
            ingested, ingested + method.onset
        )
        kwargs["active_time"] = Period(proc_time.end, proc_time.end + method.duration)
        return cls(**kwargs)

    def now_from_this(self):
        """Returns a new Dose that was taken now"""
        return self.new(self.strain, self.method)

    @property
    def status(self):
        if (n := now("utc")) in self.processing_time:
            return DoseStatus.processing
        elif n in self.active_time:
            return DoseStatus.active
        else:
            return DoseStatus.expired

    @property
    def current_period(self) -> Period | None:
        match self.status:
            case DoseStatus.processing:
                return self.processing_time
            case DoseStatus.active:
                return self.active_time
            case DoseStatus.expired:
                return None

    @property
    def prog_value(self) -> float:
        if period := self.current_period:
            return period.end.diff().total_seconds() / period.total_seconds()
        return 1

    @property
    def time_left(self) -> str:
        if period := self.current_period:
            return period.end.diff().in_words()
        return "Expired"


class DoseRow(DataRow):
    def __init__(self, dose: Dose, delete: callable, reset: callable):
        super().__init__()
        self.dose = dose
        self._status = flet.Text(str(dose.status.value))
        self._status_time_remaining = flet.Text(dose.time_left)
        self._status_progress_bar = flet.ProgressRing(value=1)
        self._prog_col = flet.Row(
            [self._status_time_remaining, self._status_progress_bar]
        )
        self.cells = [
            flet.DataCell(flet.Text(dose.strain)),
            flet.DataCell(flet.Text(dose.method.name)),
            flet.DataCell(self._status),
            flet.DataCell(self._prog_col),
            flet.DataCell(
                flet.Row(
                    [
                        flet.IconButton(
                            flet.icons.DELETE_SWEEP, on_click=partial(delete, self)
                        ),
                        flet.IconButton(
                            flet.icons.LOCK_RESET, on_click=partial(reset, self)
                        ),
                    ]
                )
            ),
        ]

    def update(self):
        ds = self.dose.status
        self._status.value = ds.value
        self._status_time_remaining.value = self.dose.time_left
        self._status_progress_bar.value = self.dose.prog_value
        match ds:
            case DoseStatus.processing:
                self._status_progress_bar.color = "Blue"
            case DoseStatus.active:
                self._status_progress_bar.color = "green"
            case DoseStatus.expired:
                self._status_progress_bar.color = "red"
        super().update()

    @property
    def status(self) -> DoseStatus:
        return self.dose.status


class DoseManager(UserControl):
    update_frequency = 0.3
    table_column_names = (
        "Strain",
        "Ingestion Method",
        "Status",
        "Time til next status",
        "Actions",
    )

    def __init__(self):
        super().__init__()
        self._dose_lock = threading.RLock()
        self._table = flet.DataTable(
            columns=[flet.DataColumn(flet.Text(i)) for i in self.table_column_names]
        )
        self._table_update_thread = threading.Thread(target=self._updater)
        self._run = False

    def add_dose(self, strain: str, method: IngestionMethod, ingested: DateTime = None):
        ingested = ingested or now("utc")
        with self._dose_lock:
            dr = DoseRow(
                Dose.new(strain, method, ingested), self.delete_dose, self.reset_dose
            )
            self._table.rows.append(dr)
        self.update()

    def delete_dose(self, dose: DoseRow, _=None):
        with self._dose_lock:
            self._table.rows.remove(dose)
        self.update()

    def reset_dose(self, dose: DoseRow, _=None):
        with self._dose_lock:
            dose.dose = dose.dose.now_from_this()
        self.update()

    def clear_expired(self, _):
        with self._dose_lock:
            to_remove = list(
                filter(lambda x: x.status is DoseStatus.expired, self._table.rows)
            )
            for dr in to_remove:
                self._table.rows.remove(dr)
        self._table.update()

    def did_mount(self):
        self._run = True
        self._table_update_thread.start()

    def will_unmount(self):
        self._run = False

    def _updater(self):
        last_duration: float | None = None

        def timer(f):
            @wraps(f)
            def inner(*args, **kwargs):
                nonlocal last_duration
                start = time.perf_counter()
                ret = f(*args, **kwargs)
                last_duration = time.perf_counter() - start

                return ret

            return inner

        @timer
        def do_update():
            with self._dose_lock:
                for row in self._table.rows:
                    row.update()

        while self._run:
            do_update()
            time.sleep(self.update_frequency - last_duration)

    def build(self):
        return self._table


class DoseUI(UserControl):
    def __init__(self, dm: DoseManager):
        self.dm = dm
        super().__init__()

    # noinspection PyAttributeOutsideInit
    def build(self):
        ingest_methods = {
            "EDIBLE": EDIBLE,
            "DRY_HERB": DRY_HERB,
            "TEST": FAKE_TEST_INGEST,
        }
        self.method_label = Text("How do you consume?")
        self.method = RadioGroup(
            content=Column(
                [
                    Radio(value="EDIBLE", label="Edibles"),
                    Radio(value="DRY_HERB", label="Dry Herb"),
                    Radio(value="TEST", label="Test"),
                ],
            ),
            value="TEST",
        )
        self.method_details = Markdown()
        self.strain = TextField(label="Strain?", value="TestStrain")
        self.when_label = Text("When did you consume it?")
        self.when_label2 = Text("How long ago? Roughly")
        self.when_units = RadioGroup(
            content=Row(
                [
                    Radio(value="minutes", label="Minutes"),
                    Radio(value="hours", label="Hours"),
                ]
            ),
            value="minutes",
        )
        self.when_value = TextField(value="0")
        self.when_extended = Column(
            controls=[self.when_label2, self.when_units, self.when_value],
            visible=False,
        )

        def change_when(e: ControlEvent):
            self.when_extended.visible = e.data == "EARLIER"
            self.when_extended.update()

        self.when = RadioGroup(
            content=Row(
                [
                    Radio(value="NOW", label="Now"),
                    Radio(value="EARLIER", label="Earlier"),
                ],
            ),
            value="NOW",
            on_change=change_when,
        )

        def add(_):
            ingested = now("utc")
            if self.when.value != "NOW":
                ingested = ingested - duration(
                    **{self.when_units.value: int(self.when_value.value)}
                )

            self.dm.add_dose(
                self.strain.value, ingest_methods[self.method.value], ingested=ingested
            )

        return Column(
            [
                self.method_label,
                self.method,
                self.strain,
                self.when_label,
                self.when,
                self.when_extended,
                Row(
                    [
                        IconButton(
                            icons.ADD,
                            icon_size=40,
                            icon_color="green",
                            on_click=add,
                            tooltip="Add new dose",
                        ),
                        IconButton(
                            icons.DELETE_SWEEP,
                            icon_size=40,
                            icon_color="red",
                            tooltip="Clear Expired doses",
                            on_click=self.dm.clear_expired,
                        ),
                    ]
                ),
            ]
        )


def main(page: flet.Page):
    page.title = "Potato"
    page.update()

    dm = DoseManager()
    du = DoseUI(dm)
    page.add(
        Row(
            controls=[dm, VerticalDivider(visible=True), du],
            vertical_alignment=flet.CrossAxisAlignment.START,
        )
    )
    dm.add_dose("Test", FAKE_TEST_INGEST)
    for _ in range(10):
        dm.add_dose(
            "expired",
            FAKE_TEST_INGEST,
        )


if __name__ == "__main__":
    flet.app(target=main)
