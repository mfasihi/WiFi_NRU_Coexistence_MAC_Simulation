import simpy


class Channel(object):
    def __init__(self, env):
        self.env = env

        self.ongoing_transmissions_gnb = list()
        self.ongoing_transmissions_ap = list()
        self.ongoing_senses_gnb = list()
        self.ongoing_senses_ap = list()
        self.bytes_sent = 0

    def check_collision(self, transmission):
        for t in self.ongoing_transmissions_gnb:
            check_end = t.end_time > transmission.start_time
            check_start = t.start_time < transmission.end_time
            check_self = transmission is not t
            if check_end and check_start and check_self:
                transmission.collided = True
                t.collided = True
        for t in self.ongoing_transmissions_ap:
            check_end = t.end_time > transmission.start_time
            check_start = t.start_time < transmission.end_time
            check_self = transmission is not t
            if check_end and check_start and check_self:
                transmission.collided = True
                t.collided = True

    def time_until_free(self):
        max_time = 0

        for t in self.ongoing_transmissions_gnb:
            time_left = t.end_time - self.env.now
            if time_left > max_time:
                max_time = time_left
        for t in self.ongoing_transmissions_ap:
            time_left = t.end_time - self.env.now
            if time_left > max_time:
                max_time = time_left

        return max_time

