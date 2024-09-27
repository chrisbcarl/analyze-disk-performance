
# encoding: utf-8
'''
The MIT License (MIT)
Copyright © 2023 Chris Carl <chris.carl@intel.com>
Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the “Software”), to
  deal in the Software without restriction, including without limitation the
  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
  sell copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
  IN THE SOFTWARE.

Author:     Chris Carl <chrisbcarl@outlook.com>
Date:       2024-09-26
Modified:   2024-09-26

Modified:
    2024-09-26 - chrisbcarl@outlook.com - complete rewrite with different modes this time
'''
# stdlib
from __future__ import print_function, division
import os
import sys
import argparse
import logging
import copy
import random
import time
import threading
import multiprocessing
import pandas as pd
from typing import Tuple

# 3rd party
import psutil

TEMP_DIRPATH = '/temp' if sys.platform == 'win32' else '/tmp'
TEMP_DIRPATH = os.path.abspath(TEMP_DIRPATH)
DRIVE, _ = os.path.splitdrive(TEMP_DIRPATH)
DATA_FILEPATH = os.path.join(TEMP_DIRPATH, 'data.dat')
PERF_FILEPATH = os.path.join(TEMP_DIRPATH, 'perf.csv')
OPERATIONS = ['perf', 'fill', 'perf+fill', 'loop']
CPU_COUNT = multiprocessing.cpu_count()
LOG_LEVELS = list(logging._nameToLevel)  # pylint: disable=(protected-access)
LOG_LEVEL = 'INFO'
FILL = -1
DURATION = 5
ITERATIONS = 10
SIZE = 1

class NiceFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawTextHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass

def create_bytearray(count, fill=FILL):
    if fill == FILL:
        new = bytearray(random.randint(0, 255) for _ in range(count))
    else:
        new = bytearray(fill for _ in range(count))
    return new

def create_bytearray_killobytes(count, fill=FILL):
    '''
    Description:
        create a bytearray by repeating only 1kb until the requested count
        the motivation is i've found generating 1MB takes about .15s, but generating 10MB takes 20s, so its not growing linearly.
    '''
    logging.debug('%s, fill=%s', count, fill)
    killobyte = create_bytearray(1024, fill=fill)
    killobytes_array = bytearray()
    for _ in range(count):
        killobytes_array.extend(copy.deepcopy(killobyte))
    logging.debug('created byte array of size %0.3f MB', len(killobytes_array) / 1024**2)
    return killobytes_array

def disk_usage_monitor(event, drive=DRIVE):
    # type: (threading.Event, str) -> None
    while not event.is_set():
        du = psutil.disk_usage(drive)
        logging.info('disk usage: %s%%', du.percent)
        for _ in range(100):
            time.sleep(1 / 100)
            if event.is_set():
                break

def validate_kwargs(
    operation=OPERATIONS[0],
    log_level='INFO',
    fill=FILL,
    size=SIZE,
    duration=DURATION,
    iterations=ITERATIONS,
    data_filepath=DATA_FILEPATH,
    perf_filepath=PERF_FILEPATH
):
    if operation not in OPERATIONS:
        raise KeyError(f'operation {operation!r} does not exist, use one of {OPERATIONS}!')
    if log_level not in LOG_LEVELS:
        raise KeyError(f'log_level {log_level!r} does not exist!')
    if size < 1:
        raise ValueError('duration must be a postive int, are you nuts?')
    if fill != -1:
        if fill < 0 and 255 < fill:
            raise ValueError('fill must be a value between [0,255] or -1')
    if duration < 0:
        raise ValueError('duration must be a postive num, are you nuts?')
    if iterations < 0:
        raise ValueError('iterations must be a postive int, are you nuts?')
    for filepath in [data_filepath, perf_filepath]:
        if not os.path.isdir(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

def write_byte_array_continuously(byte_array, data_filepath=DATA_FILEPATH, duration=DURATION, iterations=ITERATIONS):
    # type: (bytearray, str, float, int) -> Tuple[int, float, int]
    '''
    Description:
        given a bytearray, write it to the disk in write mode fashion until the duration or iterations has been exceeded
    Arguments:
        duration: float
            in seconds, how long should it go for? exec ends after duration exceeded or iteration exceeded
        iteration: int
            in ints, many times? exec ends after duration exceeded or iteration exceeded
    Returns:
        Tuple[int, float, int]
            bytes written, elapsed in seconds, iterations achieved
    '''
    validate_kwargs(data_filepath=data_filepath, duration=duration, iterations=iterations)
    logging.info('data_filepath="%s", duration=%s, iterations=%s', data_filepath, duration, iterations)
    with open(data_filepath, 'wb'):
        pass
    original_size = os.path.getsize(data_filepath)
    with open(data_filepath, 'wb') as wb:
        start = time.time()
        iteration = 0
        while time.time() - start < duration or iteration < iterations:
            wb.write(byte_array)
            iteration += 1
        end = time.time()
    bytes_written = os.path.getsize(data_filepath) - original_size
    elapsed = end - start
    throughput = bytes_written / 1024**2 / elapsed
    logging.debug('bytes_written=%s, elapsed=%s, iteration=%s, throughput=%0.3f MB/s', bytes_written, elapsed, iteration, throughput)
    return bytes_written, elapsed, iteration

def write_byte_array_contiguously(byte_array, data_filepath=DATA_FILEPATH):
    # type: (bytearray, str) -> None
    '''
    Description:
        given a bytearray, write it to the disk in an appending fashion, and when you inevitably overshoot, fill in 1mb increments
    Arguments:
    Returns:
    '''
    validate_kwargs(data_filepath=data_filepath)
    logging.info('data_filepath="%s"')

    drive, _ = os.path.splitdrive(os.path.abspath(data_filepath))

    one_mb_bytes = (1024**2)
    byte_array_bytes = len(byte_array)
    event = threading.Event()
    t = threading.Thread(target=disk_usage_monitor, args=(event, ), kwargs=dict(drive=drive), daemon=True)
    t.start()
    try:
        with open(data_filepath, 'ab') as wb:
            while psutil.disk_usage(drive).free > byte_array_bytes:
                wb.write(byte_array)
        # writing in 1mb chunks
        with open(data_filepath, 'ab') as wb:
            for i in range(byte_array_bytes // one_mb_bytes):
                if psutil.disk_usage(drive).free > one_mb_bytes:
                    one_mb_array = byte_array[i * one_mb_bytes:(i + 1) * one_mb_bytes]
                    wb.write(one_mb_array)
                else:
                    break
    except KeyboardInterrupt:
        logging.info('cancelling')
    except OSError:
        logging.info('done')
    finally:
        event.set()
    du = psutil.disk_usage(drive)
    logging.debug('disk usage: %s%%', du.percent)

def create_byte_array_high_throughput(data_filepath=DATA_FILEPATH, perf_filepath=PERF_FILEPATH, fill=FILL):
    # type: (str, str, int) -> bytearray
    '''
    Description:
        create a bunch of byte_arrays of different sizes and pick the one with the highest write throughput
    Arguments:
        fill: int
            default -1
            from 0-255, do you want the bytes to be all the same, or -1 for random?
    Returns:
        bytearray
    '''
    validate_kwargs(fill=fill, data_filepath=data_filepath, perf_filepath=perf_filepath)
    logging.info('data_filepath="%s", perf_filepath="%s", fill=%s', data_filepath, perf_filepath, fill)
    rows = []
    sweetspot_bytearray = bytearray()
    sweetspot_killobytes = 0
    sweetspot_rate = 0.0
    killobytes_list = [1, 4, 32, 128]
    killobytes_list.extend([1024 * ele for ele in killobytes_list])
    killobytes_list.extend([ele * 2 for ele in killobytes_list] + [ele * 3 for ele in killobytes_list])
    for killobytes in sorted(killobytes_list):
        megabytes = killobytes / 1024
        byte_array = create_bytearray_killobytes(killobytes, fill=fill)
        bytes_written_bytes, elapsed, iteration = write_byte_array_continuously(byte_array, data_filepath)
        bytes_written_mb = bytes_written_bytes / 1024**2
        rate = bytes_written_mb / elapsed
        if rate > sweetspot_rate:
            sweetspot_rate = rate
            sweetspot_killobytes = killobytes
            sweetspot_bytearray = byte_array
        logging.info('%s kb - %0.3f mb - %0.3f mb/s over %0.3f sec - iteration %s', killobytes, megabytes, rate, elapsed, iteration)
        row = {'kb': killobytes, 'mb': megabytes, 'rate': rate, 'elapsed': elapsed, 'iteration': iteration}
        rows.append(row)
    df = pd.DataFrame(rows)
    logging.debug('\n%s', df)
    df.to_csv(perf_filepath)
    logging.info('%s kb - %0.3f mb/s - sweetspot', sweetspot_killobytes, sweetspot_rate)
    return sweetspot_bytearray

def main():
    parser = argparse.ArgumentParser(prog='fill-the-drive', description=__doc__, formatter_class=NiceFormatter)
    operations = parser.add_subparsers(help='different operations we can do')
    op0 = operations.add_parser(
        'perf',
        help='analyze the performance of the drive which determines a file size that is fastest to write',
        description=create_byte_array_high_throughput.__doc__,
        formatter_class=NiceFormatter,
    )
    op0.set_defaults(operation='perf')
    op1 = operations.add_parser(
        'fill',
        help='fill up the disk',
        description=write_byte_array_contiguously.__doc__,
        formatter_class=NiceFormatter,
    )
    op1.set_defaults(operation='fill')
    group = op1.add_argument_group('operation specific')
    group.add_argument('--size', type=int, default=SIZE, help='size in killobytes, so --size * 1024B')
    op2 = operations.add_parser(
        'perf+fill',
        help='do perf+fill',
        description=write_byte_array_contiguously.__doc__,
        formatter_class=NiceFormatter,
    )
    op2.set_defaults(operation='perf+fill')
    op3 = operations.add_parser(
        'loop',
        help='repeatedly write to the disk for some size and duration',
        description=write_byte_array_continuously.__doc__,
        formatter_class=NiceFormatter,
    )
    op3.set_defaults(operation='loop')
    group = op3.add_argument_group('operation specific')
    group.add_argument('--size', type=int, default=SIZE, help='size in killobytes, so --size * 1024B')
    group.add_argument('--duration', type=int, default=DURATION, help='either run till --duration in seconds or --iteration is exceeded')
    group.add_argument('--iterations', type=int, default=ITERATIONS, help='either run till --duration in seconds or --iteration is exceeded')
    for op in [op0, op1, op2, op3]:
        group = op.add_argument_group('general')
        group.add_argument('--data-filepath', type=str, default=DATA_FILEPATH, help='where to dump the file that fills the disk.')
        group.add_argument('--perf-filepath', type=str, default=PERF_FILEPATH, help='where to dump the csv with performance data.')
        group.add_argument('--fill', type=int, default=FILL, help='fill bytearray with a constant byte value, default means random.')
        group.add_argument('--log-level', type=str, default=LOG_LEVEL, choices=LOG_LEVELS, help='log level')
    args = parser.parse_args()
    validate_kwargs(**vars(args))
    logging.basicConfig(format='%(asctime)s - %(levelname)10s - %(funcName)32s - %(message)s', level=args.log_level)
    logging.info('starting %r', args.operation)
    if args.operation == 'perf':
        create_byte_array_high_throughput(fill=args.fill, data_filepath=args.data_filepath, perf_filepath=args.perf_filepath)
    elif args.operation == 'perf+fill':
        sweetspot_byte_array = create_byte_array_high_throughput(data_filepath=args.data_filepath, perf_filepath=args.perf_filepath, fill=args.fill)
        write_byte_array_contiguously(sweetspot_byte_array, data_filepath=args.data_filepath)
    elif args.operation in ['fill', 'loop']:
        byte_array = create_bytearray_killobytes(args.size, fill=args.fill)
        if args.operation == 'fill':
            write_byte_array_contiguously(byte_array, data_filepath=args.data_filepath)
        elif args.operation == 'loop':
            write_byte_array_continuously(byte_array, data_filepath=args.data_filepath, duration=args.duration, iterations=args.iterations)
    logging.info('done %r', args.operation)


if __name__ == '__main__':
    main()
