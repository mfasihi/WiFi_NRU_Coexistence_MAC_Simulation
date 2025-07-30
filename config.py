from enum import Enum
from dataclasses import dataclass


class Gap(Enum):
    BEFORE = 1
    AFTER = 2
    DURING = 3
    AFTER_WITH_CCA = 4
    INSIDE = 5


class Strategy(Enum):
    GAP_PERIOD = 1
    RS_SIGNAL = 2
    CR_LBT = 3
    ECR_LBT = 4
    GCR_LBT = 5
    DB_LBT = 6


class PriorityClassValues(object):
    def __init__(self, priority_class):
        if priority_class == 1:
            self.m = 1
            self.cw_min = 3
            self.cw_max = 7
            self.mcot = 2
        elif priority_class == 2:
            self.m = 1
            self.cw_min = 7
            self.cw_max = 15
            self.mcot = 3
        elif priority_class == 3:
            self.m = 3
            self.cw_min = 15
            self.cw_max = 63
            self.mcot = 2  # ??? Should be 8, but here is 2 for DB-LBT
        elif priority_class == 4:
            self.m = 7
            self.cw_min = 15
            self.cw_max = 1023
            self.mcot = 8
        else:
            self.m = None
            self.cw_min = None
            self.cw_max = None
            self.mcot = None


@dataclass()
class Config:
    sim_time: int = 10
    debug: bool = False
    observation_slot_duration: int = 9  # microseconds
    cca_tx_switch_time: int = 0
    data_size: int = 1472  # size of payload
    max_num_gnb: int = 20
    max_num_ap: int = 20
    fairness_tolerance_rate: int = 0.2

@dataclass()
class ConfigGNB:
    poisson_lambda: int = None  # int = 10
    strategy: Strategy = Strategy.GCR_LBT
    gap_type: Gap = Gap.AFTER_WITH_CCA
    deter_period: int = 16  # Time which a node is required to wait at the start of prioritization period (us)
    _sync_slot_duration: int = 250  # microseconds (theta in cr-lbt) --> ??? should be 500, but here is 250 for DB-LBT
    mini_slot_duration: int = 36  # used by gCR_LBT --> ??? should be 36, but here is 250 for DB-LBT
    max_sync_slot_desync: int = _sync_slot_duration  # max random delay between sync slots of gNBs (us) (0 to make all gNBs synced)
    min_sync_slot_desync: int = 0  # same as above but minimum between other stations
    prioritization_slot_duration: int = 9  # microseconds
    prioritization_slot_numbers: int = 3
    priority_class: int = 3
    partial_ending_subframes: bool = False
    skip_next_slot_boundary: bool = False
    skip_next_txop: bool = False
    # only when gap_type = DURING:
    backoff_slot_split: str = "fixed"  # 'fixed' or 'variable'
    backoff_slots_to_leave: int = 7  # how many slots from the backoff procedure leave to count after the gap
    priority_class_values: PriorityClassValues = PriorityClassValues(priority_class)
    retry_limit: int = 7
    # cr-lbt parameters:
    gnb_start_point_period: int = 1000  # period of gnb's starting points (L in cr-lbt)
    t_cr_slot: int = 30  # microseconds
    t_cr_reserve: int = 8
    prob_rs_first_slot: int = 0.5  # phi in cr-lbt
    _prob_rs_next_slots: int = 0.5  # thi i cr-lbt
    _num_cr_slots: int = 6
    # db-lbt parameters:
    _switch_mode_periodicity = 11  # represents m in DB-LBT paper
    _switch_mode_threshold = 6  # represents beta in DB-LBT paper
    _initial_det_backoff_value = 20  # alpha in DB-LBT paper

    @property
    def sync_slot_duration(self) -> int:
        return self._sync_slot_duration

    @sync_slot_duration.setter
    def sync_slot_duration(self, v: int) -> None:
        self._sync_slot_duration = v

    @property
    def prob_rs_next_slots(self) -> int:
        return self._prob_rs_next_slots

    @prob_rs_next_slots.setter
    def prob_rs_next_slots(self, v: int) -> None:
        self._prob_rs_next_slots = v

    @property
    def num_cr_slots(self) -> int:
        return self._num_cr_slots

    @num_cr_slots.setter
    def num_cr_slots(self, v: int) -> None:
        self._num_cr_slots = v

    @property
    def switch_mode_periodicity(self) -> int:
        return self._switch_mode_periodicity

    @switch_mode_periodicity.setter
    def switch_mode_periodicity(self, v: int) -> None:
        self._switch_mode_periodicity = v

    @property
    def switch_mode_threshold(self) -> int:
        return self._switch_mode_threshold

    @switch_mode_threshold.setter
    def switch_mode_threshold(self, v: int) -> None:
        self._switch_mode_threshold = v

    @property
    def initial_det_backoff_value(self) -> int:
        return self._initial_det_backoff_value

    @initial_det_backoff_value.setter
    def initial_det_backoff_value(self, v: int) -> None:
        self._initial_det_backoff_value = v


@dataclass()
class ConfigAP:
    poisson_lambda: int = None  # int = 10
    cw_min: int = 15  # min cw window size
    cw_max: int = 63  # max cw window size
    r_limit: int = 7
    mcs: int = 7
    aifsn: int = 3
    RTS_threshold: int = 3000
    standard: str = "802.11a"
    nAMPDU: int = 1
    nSS: int = 1
    retry_limit: int = 7
    # db-lbt parameters:
    db_lbt: bool = False
    switch_mode_periodicity = 11  # represents m in DB-LBT paper
    switch_mode_threshold = 6  # represents beta in DB-LBT paper
    initial_det_backoff_value = 20  # alpha in DB-LBT paper
