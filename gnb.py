import numpy
import simpy
import random
import math


class GnB(object):
    def __init__(self, env, nid, config, configGNB, channel, desync, strategy, gap):
        self.env = env
        self.gap = gap
        self.strategy = strategy
        self.channel = channel
        self.nid = nid
        self.config = config
        self.configGNB = configGNB
        self.transmission_to_send = None
        self.N = None  # backoff counter
        self.next_sync_slot_boundary = 0
        self.successful_trans = 0  # number of successful transmissions
        self.total_trans = 0  # total number of transmissions
        self.total_airtime = 0  # time spent on transmitting data (including failed transmissions)
        self.successful_airtime = 0  # time spent on transmitting data (only successful transmissions)
        self.failed_transmissions_in_row = 0  # used in backoff process
        self.last_succ_trans_end_time = 0  # keeps the end time of the last successful transmission
        self.transmission_delay = 0  # channel access delay (DB-lbt paper)
        self.desync = 0  # ??? desync
        self.skip = None
        self.cr_skip = None
        self.sumTime = 0
        self.was_sent = False
        self.performing_cr_lbt = False
        self.backoff_interrupt_counter = 0
        self.s = 0  # i in DB-LBT
        self.env.process(self.sync_slot_counter())
        self.env.process(self.run())

    def set_configGNB(self, new_configGNB):
        self.configGNB = new_configGNB

    def wait_for_frame(self, time_to_wait):
        yield self.env.timeout(time_to_wait)
        self.start_generating()

    def start_generating(self):
        self.sumTime = numpy.random.exponential(1 / self.configGNB.poisson_lambda) * 1000
        self.transmission_to_send = self.generate_new_transmission()
        self.env.process(self.wait_for_frame(self.sumTime))

    def sync_slot_counter(self):
        """Process responsible for keeping the next sync slot boundary timestamp"""
        self.next_sync_slot_boundary = self.desync
        self.log("selected random sync slot offset equal to {} us".format(self.desync))
        yield self.env.timeout(self.desync)  # randomly desync tx starting points
        while True:
            self.next_sync_slot_boundary += self.configGNB.sync_slot_duration
            yield self.env.timeout(self.configGNB.sync_slot_duration)

    def wait_for_idle_channel(self):
        """Wait until the channel is sensed idle"""
        waiting_time = self.channel.time_until_free()
        while waiting_time != 0:
            self.log(f"is sensing channel busy (for at least {waiting_time} us)")
            yield self.env.timeout(waiting_time)
            waiting_time = self.channel.time_until_free()

    def sense_channel(self, slots_to_wait, isBackoff):
        try:
            while slots_to_wait > 0:
                yield self.env.timeout(self.config.observation_slot_duration)
                slots_to_wait -= 1
        except simpy.Interrupt:
            if isBackoff:
                self.backoff_interrupt_counter += 1
            pass
        return slots_to_wait

    def wait_prioritization_period(self):
        """Wait initial 16 us + m x OBSERVATION_SLOT_DURATION us"""
        m = self.configGNB.priority_class_values.m
        while m > 0:
            yield self.env.process(self.wait_for_idle_channel())
            self.log(f'channel is idle at {self.env.now}, m is {m}, waiting for deter period ({self.configGNB.deter_period} us)')
            yield self.env.timeout(self.configGNB.deter_period)

            if self.channel.time_until_free() == 0:
                self.log("Checking the channel after deter period: IDLE - wait {} observation slots".format(self.configGNB.priority_class_values.m))
            else:
                self.log("Checking the channel after deter period: BUSY - wait for idle channel")
                continue  # start the whole proces over again

            sensing_process = self.env.process(self.sense_channel(self.configGNB.priority_class_values.m, False))
            self.channel.ongoing_senses_gnb.append(sensing_process)
            m = yield sensing_process
            self.channel.ongoing_senses_gnb.remove(sensing_process)
            if m != 0:
                self.log(f"channel BUSY - prioritization period failed.", fail=True)

    def wait_gap_period(self):
        """Wait gap period"""
        backoff_time = self.N * self.config.observation_slot_duration  # time that will be taken for backoff
        time_to_next_sync_slot = self.next_sync_slot_boundary - self.env.now  # calculate time needed for gap

        gap_length = time_to_next_sync_slot - backoff_time
        while gap_length < 0:  # less than 0 means it's impossible to transmit in the next slot because backoff is too long
            gap_length += self.config.observation_slot_duration  # check if possible to transsmit in the slot after the next slot and repeat

        self.log("calculating and waiting the gap period ({:.0f} us)".format(gap_length))
        if self.configGNB.gap_type != self.gap.INSIDE:
            yield self.env.timeout(gap_length)
        else:
            self.log("waiting first half of the gap period ({:.0f} us)".format(gap_length / 2))
            yield self.env.timeout(gap_length / 2)
            self.log("(re)starting backoff procedure in the middle of the gap (slots to wait: {})".format(self.N))
            yield self.env.process(self.wait_random_backoff())
            if self.N == 0:
                self.log("waiting second half of the gap period ({:.0f} us)".format(gap_length / 2))
                yield self.env.timeout(gap_length / 2)

    def generate_new_back_off_value(self):
        if self.configGNB.strategy == self.strategy.DB_LBT:
            if (self.failed_transmissions_in_row % self.configGNB.switch_mode_periodicity < self.configGNB.switch_mode_threshold) \
                    and (self.env.now != 0):
                back_off_value = self.configGNB.initial_det_backoff_value + self.backoff_interrupt_counter
                self.backoff_interrupt_counter = 0
            else:
                back_off_value = random.randint(0, self.configGNB.switch_mode_periodicity - 1)
        else:
            cw_min = self.configGNB.priority_class_values.cw_min
            cw_max = self.configGNB.priority_class_values.cw_max
            upper_limit = (pow(2, self.failed_transmissions_in_row) * (cw_min + 1)) - 1
            upper_limit = (upper_limit if upper_limit <= cw_max else cw_max)
            back_off_value = random.randint(0, upper_limit)

        return back_off_value

    def generate_new_transmission(self):
        if self.configGNB.partial_ending_subframes:
            last_slot = random.choice([3, 6, 9, 10, 11, 12, 14])
            trans_time = (self.configGNB.priority_class_values.mcot * 1e3 - self.configGNB.sync_slot_duration) + (
                        self.configGNB.sync_slot_duration / 14) * last_slot
        else:
            trans_time = self.configGNB.priority_class_values.mcot * 1e3  # if gap in use = full MCOT to transmit data

        if self.configGNB.strategy == self.strategy.RS_SIGNAL or self.configGNB == self.strategy.DB_LBT:
            time_to_next_sync_slot = self.next_sync_slot_boundary - self.env.now  # calculate time needed for RS signal
            trans_time = (trans_time - time_to_next_sync_slot)  # if RS in use = the rest of MCOT to transmit data
            transmission = TransmissionGNB(self.env.now, trans_time, time_to_next_sync_slot)
        else:
            transmission = TransmissionGNB(self.env.now, trans_time, 0)
        return transmission

    def wait_random_backoff(self):
        if self.channel.time_until_free() > 0:
            return

        if self.configGNB.strategy == self.strategy.GAP_PERIOD and self.configGNB.gap_type == self.gap.DURING:
            if self.configGNB.backoff_slots_split == 'fixed':
                backoff_slots_left = self.configGNB.backoff_slots_to_leave
            elif self.configGNB.backoff_slots_split == 'variable':
                backoff_slots_left = int(math.ceil(self.configGNB.backoff_slots_to_leave * self.N))
            else:
                backoff_slots_left = 0

            slots_to_wait = self.N - backoff_slots_left
            slots_to_wait = slots_to_wait if slots_to_wait >= 0 else 0  # if backoff is longer than BACKOFF_SLOTS_TO_LEAVE, count these slots after gap
            self.log("will wait {} slots before stopping backoff".format(slots_to_wait))
        else:
            slots_to_wait = self.N

        sensing_process = self.env.process(self.sense_channel(slots_to_wait, True))
        self.channel.ongoing_senses_gnb.append(sensing_process)
        remaining_slots = yield sensing_process
        self.channel.ongoing_senses_gnb.remove(sensing_process)

        if self.configGNB.strategy == self.strategy.GAP_PERIOD and self.configGNB.gap_type == self.gap.DURING and remaining_slots == 0:  # redo backoff for additional backoff_slots_left
            self.log("stopping backoff and inserting gap now")
            yield self.env.process(self.wait_gap_period())
            self.log("waiting remaining backoff slots ({}) after gap".format(self.N - slots_to_wait))
            if self.channel.time_until_free() > 0:  # cca at the beginning of the backoff
                self.N = self.N - slots_to_wait
                return
            sensing_proc = self.env.process(self.sense_channel(self.N - slots_to_wait, True))
            self.channel.ongoing_senses_gnb.append(sensing_proc)
            self.N = yield sensing_proc
            self.channel.ongoing_senses_gnb.remove(sensing_proc)
        elif self.configGNB.strategy == self.strategy.GAP_PERIOD and self.configGNB.gap_type == self.gap.DURING and remaining_slots > 0:
            self.N = remaining_slots + self.N - slots_to_wait
        else:
            self.N = remaining_slots

    def transmit_gnb(self):
        transmission = self.transmission_to_send
        self.channel.ongoing_transmissions_gnb.append(transmission)
        for p in self.channel.ongoing_senses_gnb:
            if p.is_alive:
                p.interrupt()
        for p in self.channel.ongoing_senses_ap:
            if p.is_alive:
                p.interrupt()

        yield self.env.timeout(transmission.res_duration)
        yield self.env.timeout(transmission.airtime_duration)

        self.channel.check_collision(transmission)
        self.channel.ongoing_transmissions_gnb.remove(transmission)
        return not transmission.collided

    def wait_cr_slots(self):
        time_to_next_sync_slot = self.next_sync_slot_boundary - self.env.now
        k = math.floor(time_to_next_sync_slot / self.configGNB.t_cr_slot)
        if self.configGNB.strategy == self.strategy.GCR_LBT:
            k = self.configGNB.num_cr_slots

        self.log("will start {} cr-slots".format(k))

        try:
            self.performing_cr_lbt = True
            first_cr_slot = True
            sensed_idle = True

            while k > 0:
                # transmit RS for short period of cr-slot
                t = self.configGNB.t_cr_reserve
                rs_transmission = TransmissionGNB(self.env.now, t, 0)
                cr_send_first_rs_signal_proc = self.cr_send_rs_signal(t)
                self.channel.ongoing_transmissions_gnb.append(rs_transmission)
                self.log("k = {}, will start transmission of short rs signal at the beginning of cr-slot for {} us".format(k, t))
                yield self.env.process(cr_send_first_rs_signal_proc)
                self.log("k = {}, finished transmission of short rs signal at the beginning of cr-slot".format(k))
                self.channel.ongoing_transmissions_gnb.remove(rs_transmission)

                prob_rs_first_slot = 0 if self.configGNB.strategy == self.strategy.CR_LBT else self.configGNB.prob_rs_first_slot
                p = prob_rs_first_slot if first_cr_slot else self.configGNB.prob_rs_next_slots
                t_cr_remain = self.configGNB.t_cr_slot - self.configGNB.t_cr_reserve

                action = numpy.random.choice(['rs', 'sense'], 1, p=[p, 1-p])
                self.log("k = {}, will start cr-{} for {}".format(k, action, t_cr_remain))

                if action == 'rs':
                    rs_transmission = TransmissionGNB(self.env.now, t_cr_remain, 0)
                    cr_send_rs_signal_proc = self.cr_send_rs_signal(t_cr_remain)
                    self.channel.ongoing_transmissions_gnb.append(rs_transmission)
                    yield self.env.process(cr_send_rs_signal_proc)
                    self.channel.ongoing_transmissions_gnb.remove(rs_transmission)

                elif action == 'sense':
                    cr_sense_proc = self.env.process(self.cr_sense_channel(t_cr_remain))
                    self.channel.ongoing_senses_gnb.append(cr_sense_proc)
                    sensed_idle = yield cr_sense_proc
                    self.channel.ongoing_senses_gnb.remove(cr_sense_proc)

                    if not sensed_idle:
                        break

                k -= 1
                first_cr_slot = False

            if sensed_idle:
                time_to_next_sync_slot = self.next_sync_slot_boundary - self.env.now
                rs_transmission = TransmissionGNB(self.env.now, time_to_next_sync_slot, 0)
                cr_send_rs_signal_until_boundary_proc = self.cr_send_rs_signal(time_to_next_sync_slot)
                self.channel.ongoing_transmissions_gnb.append(rs_transmission)
                yield self.env.process(cr_send_rs_signal_until_boundary_proc)
                self.channel.ongoing_transmissions_gnb.remove(rs_transmission)
                self.performing_cr_lbt = False

        except simpy.Interrupt:
            pass
        return k

    def cr_send_rs_signal(self, duration):
        for p in self.channel.ongoing_senses_gnb:
            if p.is_alive:
                p.interrupt()
        for p in self.channel.ongoing_senses_ap:
            if p.is_alive:
                p.interrupt()
        yield self.env.timeout(duration)

    def cr_sense_channel(self, duration):
        if self.channel.time_until_free() > 0:
            return False

        check = False
        try:
            yield self.env.timeout(duration)
            check = True
        except simpy.Interrupt:
            pass
        return check

    def _log(self, output):
        return "{:.0f}|gNB-{}\t: {}".format(self.env.now, self.nid, output)

    def log(self, output, fail=False, success=False):
        if self.config.debug:
            if fail:
                print("\033[91m" + self._log(output) + "\033[0m")
            elif success:
                print("\033[92m" + self._log(output) + "\033[0m")
            elif self.nid == 0:
                print("\033[35m" + self._log(output) + "\033[0m")  # highlight one gNB
            else:
                print(self._log(output))

    def run(self):
        if self.configGNB.poisson_lambda is not None:
            self.start_generating()

        while True:
            self.log("begins new transmission procedure")

            if self.configGNB.poisson_lambda is None:
                self.was_sent = False

                while not self.was_sent:

                    self.N = self.generate_new_back_off_value()
                    self.log(f'has drawn a random backoff counter = {self.N}')

                    while True:  # Backoff + LBT
                        self.log(f"prioritization period has started")
                        yield self.env.process(self.wait_prioritization_period())  # Wait for prioritization period
                        self.log(f"prioritization period has finished")

                        if self.configGNB.strategy == self.strategy.GAP_PERIOD and (self.configGNB.gap_type == self.gap.BEFORE or self.configGNB.gap_type == self.gap.INSIDE):  # if RS signals not used, use gap BEFORE backoff procedure
                            yield self.env.process(self.wait_gap_period())

                        if self.configGNB.strategy == self.strategy.RS_SIGNAL \
                                or self.configGNB.strategy == self.strategy.CR_LBT \
                                or self.configGNB.strategy == self.strategy.ECR_LBT \
                                or self.configGNB.strategy == self.strategy.GCR_LBT \
                                or self.configGNB.strategy == self.strategy.DB_LBT \
                                or (self.configGNB.strategy == self.strategy.GAP_PERIOD
                                    and (self.configGNB.gap_type != self.gap.INSIDE)):  # do not wait backoff in case it was already done inside wait_gap_period
                            self.log("(re)starting backoff procedure (slots to wait: {})".format(self.N))
                            if self.N == 0 and self.configGNB.strategy == self.strategy.GAP_PERIOD and self.configGNB.gap_type == self.gap.BEFORE and self.channel.time_until_free() > 0:
                                self.log("Remaining backoff slots is 0 but channel is busy, aborting transmission")
                                continue
                            else:
                                yield self.env.process(self.wait_random_backoff())

                        if self.N == 0:
                            break
                        else:
                            self.log("Channel BUSY - backoff is frozen. Remaining slots: {}".format(self.N))

                    if self.configGNB.strategy == self.strategy.CR_LBT \
                            or self.configGNB.strategy == self.strategy.ECR_LBT \
                            or self.configGNB.strategy == self.strategy.GCR_LBT:
                        remained_cr_slots = yield self.env.process(self.wait_cr_slots())

                        if remained_cr_slots > 0 and self.performing_cr_lbt:
                            self.failed_transmissions_in_row += 1
                            self.performing_cr_lbt = False
                            self.cr_skip = self.next_sync_slot_boundary - self.env.now

                    else:
                        if self.configGNB.strategy == self.strategy.GAP_PERIOD and (self.configGNB.gap_type == self.gap.AFTER_WITH_CCA or self.configGNB.gap_type == self.gap.AFTER):
                            yield self.env.process(self.wait_gap_period())

                        if self.configGNB.strategy == self.strategy.GAP_PERIOD and (self.configGNB.gap_type == self.gap.AFTER_WITH_CCA or self.configGNB.gap_type == self.gap.INSIDE):
                            if self.channel.time_until_free() > 0:
                                self.log("Channel BUSY after gap period, aborting transmission")
                                continue

                    if self.cr_skip:
                        self.cr_skip = None
                        self.log("CR-LBT aborted - postpone the transmission - doubles the CW size - repeat backoff")
                        yield self.env.timeout(self.next_sync_slot_boundary - self.env.now)
                        continue

                    if (self.configGNB.skip_next_slot_boundary and self.skip == self.env.now) or (self.configGNB.skip_next_txop and self.skip):
                        self.skip = None
                        self.log("SKIPPING SLOT (will restart transmission procedure after {:.0f} us)".format(self.configGNB.sync_slot_duration))
                        yield self.env.timeout(self.configGNB.sync_slot_duration)
                        continue

                    # simulate short switching from sensing to TX
                    yield self.env.timeout(self.config.cca_tx_switch_time)

                    self.transmission_to_send = self.generate_new_transmission()
                    self.log(f"is now occupying the channel for the next {self.transmission_to_send.end_time - self.transmission_to_send.start_time} us")
                    self.was_sent = yield self.env.process(self.transmit_gnb())
                    self.log(f"frees the channel")

                    if self.was_sent:
                        self.log(f"transmission was successful. Current CW={self.configGNB.priority_class_values.cw_min}", success=True)
                        self.successful_trans += 1
                        self.successful_airtime += self.transmission_to_send.airtime_duration
                        self.transmission_delay += self.transmission_to_send.start_time - self.last_succ_trans_end_time
                        self.last_succ_trans_end_time = self.transmission_to_send.end_time
                        self.failed_transmissions_in_row = 0
                        if self.configGNB.skip_next_slot_boundary or self.configGNB.skip_next_txop:
                            self.skip = self.next_sync_slot_boundary
                    else:
                        self.failed_transmissions_in_row += 1
                        if self.transmission_to_send.number_of_retransmissions > self.configGNB.retry_limit:
                            self.transmission_to_send = self.generate_new_transmission()
                            self.failed_transmissions_in_row = 0
                        self.log(f"transmission resulted in a collision !!!!!!!!!!!!!!!!!!!!!", fail=True)

                    self.total_trans += 1
                    self.total_airtime += self.transmission_to_send.airtime_duration


class TransmissionGNB:
    def __init__(self, start_time, airtime_duration, res_duration=0):
        self.start_time = start_time  # transmission start time
        self.airtime_duration = airtime_duration  # transmission duration
        self.res_duration = res_duration  # reservation signal time before data transmission
        self.end_time = start_time + res_duration + airtime_duration  # transmission end time
        self.number_of_retransmissions = 0
        self.collided = False  # True when the transmission collided with another transmission
