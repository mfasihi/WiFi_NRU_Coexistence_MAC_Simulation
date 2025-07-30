import simpy
import time
import csv
import os
import random

from channel import Channel
from gnb import GnB
from ap import Ap
from config import Config, ConfigGNB, ConfigAP, Gap, Strategy


def random_sample(max_number, number, min_distance=0):
    samples = random.sample(range(max_number - (number - 1) * (min_distance - 1)), number)
    indices = sorted(range(len(samples)), key=lambda i: samples[i])
    ranks = sorted(indices, key=lambda i: indices[i])
    return [sample + (min_distance - 1) * rank for sample, rank in zip(samples, ranks)]


def run_simulation(num_of_gnb, num_of_ap, seed, desyncs=None, thi=None, num_cr_slots=None,
                   switch_mode_periodicity=None, switch_mode_threshold=None, initial_det_backoff_value=None):

    random.seed(seed)
    env = simpy.Environment()
    channel = Channel(env)
    config = Config()
    configGNB = ConfigGNB()
    if thi is not None:
        configGNB.prob_rs_next_slots = thi
    if configGNB.strategy == Strategy.GCR_LBT or configGNB.strategy == Strategy.DCRB_LBT:
        configGNB.sync_slot_duration = configGNB.mini_slot_duration
        if num_cr_slots is not None:
            configGNB.num_cr_slots = num_cr_slots

    if switch_mode_periodicity is not None:
        configGNB.switch_mode_periodicity = switch_mode_periodicity
        configGNB.switch_mode_threshold = switch_mode_threshold
        configGNB.initial_det_backoff_value = initial_det_backoff_value

    configAP = ConfigAP()

    if desyncs is None:
        """
        random desync offsets, but every value is at least MIN_SYNC_SLOT_DESYNC as far from any other value
        """
        desyncs = random_sample(
            configGNB.max_sync_slot_desync - configGNB.min_sync_slot_desync, num_of_gnb, configGNB.min_sync_slot_desync)
        """
        random offset from a set (set contains values with step of MIN_SYNC_SLOT_DESYNC)
        desync_set = list(np.linspace(0, MAX_SYNC_SLOT_DESYNC, num=int(MAX_SYNC_SLOT_DESYNC/MIN_SYNC_SLOT_DESYNC)+1))[:-1]
        desyncs = [random.choice(desync_set) for _ in range(0, nr_of_gnbs)]
        """

    gnb_list = list()
    ap_list = list()

    for i in range(num_of_gnb):
        gnb = GnB(env, i, config, configGNB, channel, desyncs[i], Strategy, Gap)
        gnb_list.append(gnb)

    for j in range(num_of_ap):
        ap = Ap(env, j, config, configAP, channel)
        ap_list.append(ap)

    env.run(until=(Config.sim_time * 1e6))

    results = list()
    for gnb in gnb_list:
        results.append({'id': gnb.nid,
                        'type': 'gnb',
                        'succ_trans': gnb.successful_trans,
                        'fail_trans': gnb.total_trans - gnb.successful_trans,
                        'total_trans': gnb.total_trans,
                        'coll_percent': 1 - gnb.successful_trans / gnb.total_trans if gnb.total_trans > 0 else None,
                        'total_airtime': gnb.total_airtime,
                        'succ_airtime': gnb.successful_airtime,
                        'trans_delay': gnb.transmission_delay / gnb.successful_trans})

    for ap in ap_list:
        results.append({'id': ap.nid,
                        'type': 'ap',
                        'succ_trans': ap.successful_trans,
                        'fail_trans': ap.total_trans - ap.successful_trans,
                        'total_trans': ap.total_trans,
                        'coll_percent': 1 - ap.successful_trans / ap.total_trans if ap.total_trans > 0 else None,
                        'total_airtime': ap.total_airtime,
                        'succ_airtime': ap.successful_airtime,
                        'trans_delay': ap.transmission_delay / ap.successful_trans})

    return results


def process_results(results, seed, num_of_gnb, num_of_ap, filename, thi=None, num_cr_slots=None,
                    switch_mode_periodicity=None, switch_mode_threshold=None, initial_det_backoff_value=None):
    total_airtime_gnb = 0
    trans_total_gnb = 0
    fail_total_gnb = 0
    succ_total_gnb = 0
    succ_airtime_gnb = 0
    trans_delay_gnb = 0

    total_airtime_ap = 0
    trans_total_ap = 0
    fail_total_ap = 0
    succ_total_ap = 0
    succ_airtime_ap = 0
    trans_delay_ap = 0

    configGNB = ConfigGNB()
    per_gnb_airtime = {}
    per_ap_airtime = {}
    per_gnb_delay = {}
    per_ap_delay = {}
    for i in range(Config.max_num_gnb):
        per_gnb_airtime["norm_gnb_{}_airtime".format(i)] = 0
        per_gnb_delay["norm_gnb_{}_delay".format(i)] = 0
    for j in range(Config.max_num_ap):
        per_ap_airtime["norm_ap_{}_airtime".format(j)] = 0
        per_ap_delay["norm_ap_{}_delay".format(j)] = 0

    i = 0
    j = 0
    for res in results:
        if res['type'] == 'gnb':
            per_gnb_airtime["norm_gnb_{}_airtime".format(i)] = res['total_airtime']
            per_gnb_delay["norm_gnb_{}_delay".format(i)] = res['trans_delay']
            total_airtime_gnb += res['total_airtime']
            trans_total_gnb += res['total_trans']
            fail_total_gnb += res['fail_trans']
            succ_total_gnb += res['succ_trans']
            succ_airtime_gnb += res['succ_airtime']
            trans_delay_gnb += res['trans_delay']
            i = i + 1
        elif res['type'] == 'ap':
            per_ap_airtime["norm_ap_{}_airtime".format(j)] = res['total_airtime']
            per_ap_delay["norm_ap_{}_delay".format(j)] = res['trans_delay']
            total_airtime_ap += res['total_airtime']
            trans_total_ap += res['total_trans']
            fail_total_ap += res['fail_trans']
            succ_total_ap += res['succ_trans']
            succ_airtime_ap += res['succ_airtime']
            trans_delay_ap += res['trans_delay']
            j = j + 1

    now = time.localtime()

    sum_sq_ap = 0
    sum_sq_gnb = 0
    for res in results:
        if res['type'] == 'ap':
            sum_sq_ap += res['succ_airtime'] ** 2
        else:
            sum_sq_gnb += res['succ_airtime'] ** 2

    jfi_ap = (succ_airtime_ap ** 2) / (Config.max_num_ap * sum_sq_ap) if Config.max_num_ap != 0 else 0
    jfi_gnb = (succ_airtime_gnb ** 2) / (Config.max_num_gnb * sum_sq_gnb) if Config.max_num_gnb != 0 else 0
    jfi_total = ((succ_airtime_gnb + succ_airtime_ap) ** 2) / (2 * (succ_airtime_gnb ** 2 + succ_airtime_ap ** 2))

    ret = {
        "time": time.strftime("%H:%M:%S", now),
        "fail_total_gnb": fail_total_gnb,
        "fail_total_ap": fail_total_ap,
        "succ_total_gnb": succ_total_gnb,
        "succ_total_ap": succ_total_ap,
        "trans_total_gnb": trans_total_gnb,
        "trans_total_ap": trans_total_ap,
        "throughput_gnb": (succ_total_gnb * Config.data_size * 8) / (Config.sim_time * 1e6),
        "throughput_ap": (succ_total_ap * Config.data_size * 8) / (Config.sim_time * 1e6),
        "total_airtime_gnb": total_airtime_gnb,
        "total_airtime_ap": total_airtime_ap,
        "collision_percent_gnb": fail_total_gnb / trans_total_gnb if (num_of_gnb != 0 and trans_total_gnb != 0) else 0,
        "collision_percent_ap": fail_total_ap / trans_total_ap if (num_of_ap != 0 and trans_total_ap != 0) else 0,
        "efficiency_gnb": succ_airtime_gnb / (Config.sim_time * 1e6),
        "efficiency_ap": succ_airtime_ap / (Config.sim_time * 1e6),
        "trans_delay_ap": trans_delay_ap,
        "trans_delay_gnb": trans_delay_gnb,
        "trans_delay_total": trans_delay_ap + trans_delay_gnb,
        "jfi_ap": jfi_ap,
        "jfi_gnb": jfi_gnb,
        "jfi_total": jfi_total
    }

    for i in range(len(per_gnb_airtime)):
        per_gnb_airtime["norm_gnb_{}_airtime".format(i)] = per_gnb_airtime["norm_gnb_{}_airtime".format(i)] / total_airtime_gnb

    for j in range(len(per_ap_airtime)):
        per_ap_airtime["norm_ap_{}_airtime".format(j)] = per_ap_airtime["norm_ap_{}_airtime".format(j)] / total_airtime_ap

    ret.update(per_gnb_airtime)
    ret.update(per_gnb_delay)
    ret.update(per_ap_airtime)
    ret.update(per_ap_delay)

    parameters = {'sim_time': Config.sim_time,
                  'seed': seed,
                  'num_gnbs': num_of_gnb,
                  'num_aps': num_of_ap,
                  'num_total': num_of_gnb + num_of_ap,
                  'strategy': configGNB.strategy,
                  'gap_type': configGNB.gap_type if configGNB.strategy == Strategy.GAP_PERIOD else "N/A",
                  'num_cr_slots': configGNB.num_cr_slots if num_cr_slots is None else num_cr_slots,
                  'switch_mode_periodicity': configGNB.switch_mode_periodicity if switch_mode_periodicity is None else switch_mode_periodicity,
                  'switch_mode_threshold': configGNB.switch_mode_threshold if switch_mode_threshold is None else switch_mode_threshold,
                  'initial_det_backoff_value': configGNB.initial_det_backoff_value if initial_det_backoff_value is None else initial_det_backoff_value,
                  'cw_min': configGNB.priority_class_values.cw_min,
                  'cw_max': configGNB.priority_class_values.cw_max,
                  'thi': configGNB.prob_rs_next_slots if thi is None else thi,
                  'mcot': configGNB.priority_class_values.mcot,
                  'sync': configGNB.sync_slot_duration,
                  'partial': configGNB.partial_ending_subframes}

    dump_csv(parameters, ret, filename + '.csv')
    return ret


def dump_csv(parameters, results, filename=None):
    filename = filename if filename else 'results.csv'
    filename = 'results/' + filename
    write_header = True
    if os.path.isfile(filename):
        write_header = False
    with open(filename, mode='a') as csv_file:
        results.update(parameters)
        fieldnames = results.keys()
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(results)


def log_results(sim_results, start_time, end_time, processed):
    for result in sim_results:
        print("------------------------------------")
        node_type = result['type']
        print(node_type, '-', result['id'])
        print('Collisions: {}/{} ({}%)'.format(result['fail_trans'],
                                               result['total_trans'],
                                               result['coll_percent'] * 100 if result[
                                                                                   'coll_percent'] is not None else 'N/A'))
        print('Total airtime: {} ms'.format(result['total_airtime'] / 1e3))
        channel_efficiency = 0
        if node_type == 'gnb':
            channel_efficiency = result['total_airtime'] / processed['total_airtime_gnb'] if processed[
                                                                                                 'total_airtime_gnb'] != 0 else 0
        elif node_type == 'ap':
            channel_efficiency = result['total_airtime'] / processed['total_airtime_ap'] if processed[
                                                                                                 'total_airtime_ap'] != 0 else 0
        print('Channel efficiency: {:.2f}'.format(channel_efficiency))

    print('====================================')
    print('Total collision probability gNB: {:.4f}'.format(processed['collision_percent_gnb']))
    print('Total channel efficiency gNB: {:.4f}'.format(processed['efficiency_gnb']))
    print('Total collision probability AP: {:.4f}'.format(processed['collision_percent_ap']))
    print('Total channel efficiency AP: {:.4f}'.format(processed['efficiency_ap']))

    print("Jain's fairness index AP: {:.4f}".format(processed['jfi_ap']))
    print("Jain's fairness index GNB: {:.4f}".format(processed['jfi_gnb']))
    print("Jain's fairness index Total: {:.4f}".format(processed['jfi_total']))
    print('====================================')
    print("--- Simulation ran for %s seconds ---" % (end_time - start_time))


def network_performance_vs_num_gnb(num_gnb_list, num_ap, equal_num_nodes=False):
    method = ConfigGNB.gap_type if ConfigGNB.strategy == Strategy.GAP_PERIOD else ConfigGNB.strategy
    for num_gnb in num_gnb_list:
        sl = []
        for _ in range(10):
            sl.append(random.randint(10, 1000))

        print("SEEDS: ", sl)
        for s in sl:
            print('seed #{} - #ap/gnb: {}/{}'.format(s, num_gnb, num_gnb))
            st = time.time()
            sr = run_simulation(num_gnb, num_gnb if equal_num_nodes else num_ap, s)
            et = time.time()
            p = process_results(sr, s, num_gnb, num_gnb if equal_num_nodes else num_ap,
                                f"network_performance_vs_num_{'gnb-ap' if equal_num_nodes else 'gnb'}_{method}")
            log_results(sr, st, et, p)


def nru_efficiency_vs_thi(num_gnb, num_ap):
    thi_list = [i/10 for i in range(0, 11)]
    for thi in thi_list:
        sl = []
        for _ in range(10):
            sl.append(random.randint(10, 1000))
        print("SEEDS: ", sl)
        for s in sl:
            st = time.time()
            sr = run_simulation(num_gnb, num_ap, s, None, thi)
            et = time.time()
            p = process_results(sr, s, num_gnb, num_ap, f"nru_efficiency_vs_thi", thi)
            log_results(sr, st, et, p)


def per_node_performance_cdf(num_gnb, num_ap):
    method = ConfigGNB.gap_type if ConfigGNB.strategy == Strategy.GAP_PERIOD else ConfigGNB.strategy
    sl = []
    for _ in range(10):
        sl.append(random.randint(10, 1000))

    print("SEEDS: ", sl)
    for s in sl:
        st = time.time()
        sr = run_simulation(num_gnb, num_ap, s)
        et = time.time()
        p = process_results(sr, s, num_gnb, num_ap, f"per_node_performance_cdf_{method}")
        log_results(sr, st, et, p)


def network_performance_vs_num_gnb_DB_LBT(num_gnb_list, num_ap, equal_num_nodes=False):
    switch_mode_periodicity = [4, 7, 10]
    switch_mode_threshold = [3, 5, 8]
    initial_det_backoff_value = [11, 16, 21]

    for num_gnb in num_gnb_list:
        for i in range(3):
            sl = []
            for _ in range(10):
                sl.append(random.randint(10, 1000))
            print("SEEDS: ", sl)
            for s in sl:
                st = time.time()
                sr = run_simulation(num_gnb, num_gnb if equal_num_nodes else num_ap, s, None, None, None,
                                    switch_mode_periodicity[i], switch_mode_threshold[i], initial_det_backoff_value[i])
                et = time.time()
                p = process_results(sr, s, num_gnb, num_gnb if equal_num_nodes else num_ap, "network_performance_db_lbt", None, None,
                                    switch_mode_periodicity[i], switch_mode_threshold[i], initial_det_backoff_value[i])
                log_results(sr, st, et, p)


if __name__ == "__main__":
    network_performance_vs_num_gnb([i for i in range(1, Config.max_num_gnb + 1)], Config.max_num_ap, True)
