import numpy
import simpy
import random
from times import *
RTS_global_flag = True
RTS_transmitter = ""


class Ap(object):
    def __init__(self, env, nid, config, configAP, channel):
        self.env = env
        self.channel = channel
        self.nid = nid
        self.config = config
        self.configAP = configAP
        self.frame_to_send = None
        self.times = Times(config.data_size, configAP.mcs, configAP.aifsn, configAP.standard, configAP.nSS)
        self.N = None  # backoff counter
        self.successful_trans = 0  # number of successful transmissions
        self.total_trans = 0  # total number of transmissions
        self.total_airtime = 0  # time spent on transmitting data (including failed transmissions)
        self.successful_airtime = 0  # time spent on transmitting data (only successful transmissions)
        self.failed_transmissions_in_row = 0  # used in backoff process
        self.last_succ_trans_end_time = 0  # keeps the end time of the last successful transmission
        self.transmission_delay = 0
        self.sumTime = 0
        self.skip = False
        self.was_sent = False
        self.backoff_interrupt_counter = 0  # i in DB-LBT
        self.env.process(self.run())

    def wait_for_frame(self, time_to_wait):
        yield self.env.timeout(time_to_wait)
        self.start_generating()

    def start_generating(self):
        self.sumTime = numpy.random.exponential(1 / self.configAP.poisson_lambda) * 1000
        self.frame_to_send = self.generate_new_frame()
        self.env.process(self.wait_for_frame(self.sumTime))

    def generate_new_frame(self):
        trans_time = self.times.get_ppdu_frame_time(self.configAP.nAMPDU)
        return TransmissionAP(self.env.now, trans_time, self.config.data_size)

    def sense_channel(self, slots_to_wait):
        try:
            while slots_to_wait > 0:
                yield self.env.timeout(self.config.observation_slot_duration)
                slots_to_wait -= 1
        except simpy.Interrupt:
            self.backoff_interrupt_counter += 1
            pass
        return slots_to_wait

    def generate_new_back_off_value(self):
        if self.configAP.db_lbt:
            if (self.failed_transmissions_in_row % self.configAP.switch_mode_periodicity < self.configAP.switch_mode_threshold) \
                    and (self.env.now != 0):
                back_off_value = self.configAP.initial_det_backoff_value + self.backoff_interrupt_counter
                self.backoff_interrupt_counter = 0
            else:
                back_off_value = random.randint(0, self.configAP.switch_mode_periodicity - 1)
        else:
            cw_min = self.configAP.cw_min
            cw_max = self.configAP.cw_max
            upper_limit = (pow(2, self.failed_transmissions_in_row) * (cw_min + 1)) - 1
            upper_limit = (upper_limit if upper_limit <= cw_max else cw_max)
            back_off_value = random.randint(0, upper_limit)

        return back_off_value

    def wait_random_backoff(self):
        if self.channel.time_until_free() > 0:
            return

        sensing_process = self.env.process(self.sense_channel(self.N))
        self.channel.ongoing_senses_ap.append(sensing_process)
        remaining_slots = yield sensing_process
        self.channel.ongoing_senses_ap.remove(sensing_process)
        self.N = remaining_slots

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

    def transmit_ap(self):
        transmission = self.frame_to_send
        self.channel.ongoing_transmissions_ap.append(transmission)
        for p in self.channel.ongoing_senses_gnb:
            if p.is_alive:
                p.interrupt()
        for p in self.channel.ongoing_senses_ap:
            if p.is_alive:
                p.interrupt()

        yield self.env.timeout(transmission.airtime_duration)

        self.channel.check_collision(transmission)
        self.channel.ongoing_transmissions_ap.remove(transmission)
        return not transmission.collided

    def _log(self, output):
        return "{:.0f}|AP-{}\t: {}".format(self.env.now, self.nid, output)

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
        if self.configAP.poisson_lambda is not None:
            self.start_generating()
        global RTS_global_flag

        # while True:
        self.log("begins new transmission procedure")

        if self.configAP.poisson_lambda is None:
            self.was_sent = False

            while not self.was_sent:

                self.N = self.generate_new_back_off_value()
                self.log(f'has drawn a random backoff counter = {self.N}')

                while True:  # CSMA/CA
                    self.log("(re)starting backoff procedure with DIFS (slots to wait: {})".format(self.N))
                    yield self.env.timeout(self.times.DIFSTime)
                    yield self.env.process(self.wait_random_backoff())

                    if self.N == 0:
                        self.log("Backoff has ended - wait for short switching time from sensing to tx: {}".format(
                            self.config.cca_tx_switch_time))
                        yield self.env.timeout(self.config.cca_tx_switch_time)  # Short switching from sensing to TX
                        break
                    else:
                        self.log("Channel BUSY - backoff is frozen. Remaining slots: {}".format(self.N))

                self.frame_to_send = self.generate_new_frame()
                self.log(f"is now occupying the channel for the next {self.frame_to_send.airtime_duration} us")
                self.was_sent = yield self.env.process(self.transmit_ap())
                self.log(f"frees the channel")

                if self.was_sent:
                    yield self.env.timeout(self.times.get_ack_frame_time())  # wait ack
                    self.log(f"transmission was successful. Current CW={self.configAP.cw_min}", success=True)
                    self.successful_trans += 1
                    self.successful_airtime += self.frame_to_send.airtime_duration
                    self.failed_transmissions_in_row = 0
                    self.transmission_delay += self.frame_to_send.start_time - self.last_succ_trans_end_time
                    self.last_succ_trans_end_time = self.frame_to_send.end_time
                    self.channel.bytes_sent += self.frame_to_send.data_size
                else:
                    self.failed_transmissions_in_row += 1
                    yield self.env.timeout(self.times.ack_timeout)
                    if self.frame_to_send.number_of_retransmissions > self.configAP.retry_limit:
                        self.frame_to_send = self.generate_new_frame()
                        self.failed_transmissions_in_row = 0
                    self.log(f"transmission resulted in a collision !!!!!!!!!!!!!!!!!!!!!", fail=True)

                self.total_trans += 1
                self.total_airtime += self.frame_to_send.airtime_duration


class TransmissionAP:
    def __init__(self, start_time, airtime_duration, data_size):
        self.start_time = start_time
        self.airtime_duration = airtime_duration
        self.data_size = data_size
        self.end_time = start_time + airtime_duration
        self.number_of_retransmissions = 0
        self.collided = False
