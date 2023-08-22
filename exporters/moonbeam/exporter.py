#!/usr/bin/env python3

import threading
import requests
import yaml
import time
import json
import logging
from numpy import median, average, percentile
from decimal import *
from collections import deque
from flask import Flask, request, make_response

logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO, datefmt='%Y-%m-%d %I:%M:%S')
app = Flask(__name__)

@app.route("/metrics")
def metrics():
    chain = get_config('chain')
    metrics = q_metrics[0].copy()

    out = ""

    try:
        out += '# HELP moonbeam_currentRound Current round\n'
        out += '# TYPE moonbeam_round Current round counter\n'

        out += 'moonbeam_currentRound{chain="%s"} %s\n' % (chain,metrics['common']['current_round'])
    except KeyError:
        pass

    try:
        out += '# HELP moonbeam_activeCollatorsCount Active collators\n'
        out += '# TYPE moonbeam_activeCollatorsCount Active collators counter\n'

        out += 'moonbeam_activeCollatorsCount{chain="%s"} %s\n' % (chain,metrics['common']['active_collators'])
    except KeyError:
        pass

    try:
        out += '# HELP moonbeam_roundBlocks Round blocks\n'
        out += '# TYPE moonbeam_roundBlocks Round blocks counter\n'

        out += 'moonbeam_roundBlocks{chain="%s"} %s\n' % (chain,metrics['common']['rnd_blocks'])
    except KeyError:
        pass

    try:
        out += '# HELP moonbeam_blocksAvg Blocks avarage\n'
        out += '# TYPE moonbeam_blocksAvg Blocks avarage counter\n'

        out += 'moonbeam_blocksAvg{chain="%s"} %s\n' % (chain,metrics['common']['average'])
    except KeyError:
        pass

    try:
        out += '# HELP moonbeam_blocksMedian Blocks median\n'
        out += '# TYPE moonbeam_blocksMedian Blocks median counter\n'

        out += 'moonbeam_blocksMedian{chain="%s" } %s\n' % (chain,metrics['common']['median'])
    except KeyError:
        pass

    try:
        out += '# HELP moonbeam_blocksP95 Blocks p95\n'
        out += '# TYPE moonbeam_blocksP95 Blocks p95 counter\n'

        out += 'moonbeam_blocksP95{chain="%s"} %s\n' % (chain,metrics['common']['p95'])
    except KeyError:
        pass

    try:
        out += '# HELP moonbeam_blockAuthorship Block authors\n'
        out += '# TYPE moonbeam_blockAuthorship Block authors counter\n'

        for k,v in metrics['collators'].items():
            out += 'moonbeam_blockAuthorship{chain="%s",account="%s"} %s\n' % (chain,k,v)
    except KeyError:
        pass
 
    try:
        out += '# HELP moonbeam_rooundProgress Round progress\n'
        out += '# TYPE moonbeam_roundProgress Round progress counter\n'

        out += 'moonbeam_roundProgress{chain="%s"} %s\n' % (chain,metrics['common']['round_progress'])
    except KeyError:
        pass

    response = make_response(out, 200)
    response.mimetype = "text/plain"

    return response

def api_request(method = None,args = None):
    url = get_config('api_substrate')

    if isinstance(args, list):
        for i in range(len(args)):
            if isinstance(args[i], str):
                args[i] = '"' + args[i] + '"'
    elif isinstance(args, str):
        args = '"' + args + '"'
    elif not args:
        args = ""

    data = {'method': method,
            'args': args}

    try:
        r = requests.post(url, json=data)
    except (ConnectionRefusedError,requests.exceptions.ConnectionError) as e:
        logging.critical(e)
        return None

    if r.status_code == 200:
        return r.json()['result']
    else:
        logging.critical('Request to ' + url + ' finished with code ' + str(r.status_code))
        return None

def get_round_progress(chain):
    constants = {
                 'moonbeam':{'round_length':1800},
                 'moonriver':{'round_length':600}
                }

    round_length = constants[chain]['round_length']
    round_first_block = api_request(method = 'api.query.parachainStaking.round')['first']
    current_block = int(api_request(method = 'api.query.system.number'),16)
    round_progress = (int(current_block) - int(round_first_block)) / round_length * 100

    return round_progress

def get_config(part):
    with open('./config.yaml') as config_file:
        data = yaml.load(config_file, Loader=yaml.FullLoader)
    
    return data[part]

def main():
    block = 0
    rnd = 0

    while True:
        try:
            current_rnd = api_request(method = 'api.query.parachainStaking.round')['current']
            if current_rnd != rnd:
                rnd_blocks_count = 0
                
                active_collators = api_request(method = 'api.query.parachainStaking.selectedCandidates') 
                common = {}
                common['active_collators'] = len(active_collators)
                common['current_round'] = current_rnd
                common['rnd_blocks'] = 0
                authored_blocks_count = 0
                all_collators = {k:authored_blocks_count for k in active_collators}
                result = {'collators':all_collators, 'common':common}
                logging.info('New round ' + str(current_rnd) + ' has just begun')
                
            last_block = int(api_request(method = 'api.query.system.number'),16)
            
            if  last_block != block:
                logging.info('Processing block ' + str(last_block))
               
                block_author = api_request(method = 'api.query.authorInherent.author')
                                    
                for addr,params in result['collators'].items():
                                                         
                    if block_author == addr:
                       result['collators'][addr] += 1
                       
                        
                       logging.info('Collator ' + str(addr) + ' has just constructed block ' + str(last_block))
                
                result['common']['round_progress'] = int(get_round_progress(get_config('chain')))
                result['common']['rnd_blocks'] += 1

                result['common']['median'] = int(Decimal(median(list(all_collators.values()))))
                result['common']['average'] = int(Decimal(average(list(all_collators.values()))))
                result['common']['p95'] = int(Decimal(percentile(list(all_collators.values()),95)))
                
                q_metrics.clear()
                q_metrics.append(result)

            rnd = current_rnd
            block = last_block

        except Exception as e:
            logging.critical('The main thread been stucked with error "' + str(e) + '"')
            time.sleep(5)
            continue

        time.sleep(3)

if __name__ == '__main__':
    endpoint_listen = get_config('exporter')['listen']
    endpoint_port = get_config('exporter')['port']
       
    collators = {}

   # for k,v in get_config('validators').items():
   #     collators[v['account']] = {'node':k}

    q_metrics = deque([])

    worker = threading.Thread(target=main)
    worker.daemon = True
    worker.start()

    app.run(host="0.0.0.0", port=int(endpoint_port))
