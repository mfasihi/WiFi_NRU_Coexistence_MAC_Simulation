import math
import string

# MCS: Modulation and Coding Scheme [Data rate, Control rate]
# 802.11a
MCS = {
    0: [6, 6],
    1: [9, 6],
    2: [12, 12],
    3: [18, 12],
    4: [24, 24],
    5: [36, 24],
    6: [48, 24],
    7: [54, 24],
}
# 802.11ac
MCS_ac = {
    0: [6.5, 6],
    1: [13, 12],
    2: [19.5, 12],
    3: [26, 24],
    4: [39, 24],
    5: [52, 24],
    6: [58.5, 24],
    7: [65, 24],
    8: [78, 24],
}


class Times:
    aSlotTime = 9  # [us]
    aSIFSTime = 16  # [us]
    DIFSTime = 16 + 3 * 9
    ack_timeout = 44  # [us]
    mac_overhead = 40 * 8  # [b]
    ack_size = 14 * 8  # [b]
    _overhead = 22  # [b] --> OFDM service (16 bits) + Tail (6 bits)

    def __init__(self, payload: int = 1024, mcs: int = 7, aIFSn: int = 3, standard: string = "802.11a", nss: int = 3):
        """
        :param payload: maximum length allowed for packet payloads
        :param mcs: modulation and coding scheme index
        :param aIFSn: arbitrary inter-frame space number
        :param standard: 802.11a or 802.11ac
        :param nss: number of spatial streams supported by 802.11ac (up to 8)
        """
        self.payload = payload
        self.mcs = mcs
        self.nss = nss

        if standard == "802.11a":
            self.phy_data_rate = MCS[mcs][0] * pow(10, -6)  # [Mb/us] Possible values 6, 9, 12, 18, 24, 36, 48, 54
            self.phy_ctr_rate = MCS[mcs][1] * pow(10, -6)  # [Mb/us]
            self.data_rate = MCS[mcs][0]  # [b/us]
            self.ctr_rate = MCS[mcs][1]  # [b/us]
        elif standard == "802.11ac":
            self.phy_data_rate = nss * MCS_ac[mcs][0] * pow(10, -6)  # [Mb/us]
            self.phy_ctr_rate = MCS_ac[mcs][1] * pow(10, -6)  # [Mb/us]
            self.data_rate = nss * MCS_ac[mcs][0]  # [b/us]
            self.ctr_rate = MCS_ac[mcs][1]  # [b/us]

        self.n_data = 4 * self.phy_data_rate  # [b/symbol] ???
        self.n_ctr = 4 * self.phy_ctr_rate  # [b/symbol] ???
        self.OFDMPreamble = 16  # [us]
        self.OFDMSignal = 24 / self.ctr_rate  # [us]
        self.aIFSn = aIFSn
        self.DIFSTime = aIFSn * Times.aSlotTime + Times.aSIFSTime

    def get_ppdu_frame_time(self, nAMPDU):
        """
        :param nAMPDU: number of MPDU sub-frames aggregated with a single leading PHY header
        """
        msdu = self.payload * 8  # Mac Service Data Unit
        mac_frame = nAMPDU * Times.mac_overhead + msdu  # [b] --> MAC Frame
        ppdu_padding = math.ceil(
            (Times._overhead + mac_frame) / self.n_data
        ) * self.n_data - (Times._overhead + mac_frame)  # [b] --> PPDU padding bits
        cpsdu = Times._overhead + mac_frame + ppdu_padding  # [b] --> CPSDU Frame
        ppdu = self.OFDMPreamble + self.OFDMSignal + cpsdu / self.data_rate  # [us]
        ppdu_tx_time = math.ceil(ppdu)  # [us]
        return ppdu_tx_time

    def get_ack_frame_time(self):
        ack = Times._overhead + Times.ack_size  # [b]
        ack = self.OFDMPreamble + self.OFDMSignal + ack / self.ctr_rate  # [us]
        ack_tx_time = Times.aSIFSTime + ack
        return math.ceil(ack_tx_time)

    def get_rts_cts_time(self):
        # RTS Packet = 14 bytes = 160 bits
        # CTS Packet = 20 bytes = 112 bits
        return 2 * Times.aSIFSTime + (14 * 8 / self.ctr_rate) + Times.DIFSTime + (20 * 8 / self.ctr_rate)




