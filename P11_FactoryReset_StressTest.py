#!/usr/bin/env python3

import sys
import time
import csv
from datetime import datetime
from subprocess import run

SERIAL_NUMBER = None
REBOOT_TIMES = None
FACTORY_RESET_COMMAND = 'am broadcast -a android.intent.action.FACTORY_RESET -n android/com.android.server.MasterClearReceiver'
SKIP_OOBE =  'am broadcast -a com.google.android.clockwork.action.TEST_MODE'

MAX_REBOOT_TIME_SEC = 900 # 15 minutes


def logging(f, info):
    log = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {info}"
    f.write(log + '\n')
    f.flush()
    print(log)


def run_factory_reset(serial, f):
    # Gain root first
    logging(f, "Gaining ADB root before factory reset...")
    result = run(['adb', '-s', serial, 'root'], capture_output=True, text=True)
    if result.returncode != 0:
        logging(f, f"Failed to gain root: {result.stderr}")
        return False
    if "adbd cannot run as root" in result.stdout.lower():
        logging(f, "Device does not allow ADB root. Cannot proceed with factory reset.")
        return False
    logging(f, "ADB root granted successfully.")

    # Trigger factory reset
    logging(f, "Initiating factory reset")
    result = run(['adb', '-s', serial, 'shell', FACTORY_RESET_COMMAND], capture_output=True, text=True)
    if result.returncode != 0:
        logging(f, f"Failed to start factory reset: {result.stderr}")
        return False

    # Wait for device to go offline
    logging(f, "Waiting for device to go offline...")
    start_wait = time.time()
    while True:
        time.sleep(2)
        devices = run(['adb', 'devices'], capture_output=True, text=True).stdout
        if serial not in devices or f"{serial}\toffline" in devices:
            logging(f, "Device went offline. Reset in progress...")
            break
        if time.time() - start_wait > 60:
            logging(f, "Timeout waiting for device to go offline. Continuing anyway...")
            break

    return True


def wait_for_boot_and_oobe(serial, f):
    logging(f, "Waiting for device to come back online after reset...")
    start_time = time.time()

    # Wait for device to be detected again
    while True:
        time.sleep(5)
        devices = run(['adb', 'devices'], capture_output=True, text=True).stdout
        if serial in devices and "device" in devices:
            logging(f, "Device detected by ADB.")
            break

    # Wait for boot completion
    while True:
        result = run(['adb', '-s', serial, 'shell', 'getprop', 'sys.boot_completed'], capture_output=True, text=True)
        if result.stdout.strip() == '1':
            logging(f, "System boot completed.")
            break
        time.sleep(5)

    # Wait until OOBE "Tap to Begin" appears
    logging(f, "Waiting for OOBE (Tap to Begin) screen...")
    while True:
        result = run(['adb', '-s', serial, 'shell', 'dumpsys', 'window', 'windows'], capture_output=True, text=True)
        if "Tap to Begin" in result.stdout or "SetupWizard" in result.stdout:
            logging(f, "OOBE screen detected.")
            break
        time.sleep(5)

    end_time = time.time()
    reboot_time = end_time - start_time
    completed_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logging(f, f"Reboot + OOBE completed in {reboot_time:.2f} seconds at {completed_time}")
    time.sleep(80) #This sleep is added just to make sure device completely finishes whole process of booting before next Factory Reset cycle

    # Run below command to skip OOBE and Get the watch ready for next iteration
    logging(f, "SKIPPING OOBE, so starting TEST MODE")
    result = run(['adb', '-s', serial, 'shell', SKIP_OOBE], capture_output=True, text=True)
    if result.returncode != 0:
        logging(f, f"Failed to start TEST MODE {result.stderr}")
        return False

    time.sleep(120) #This sleep is added just to make sure TEST MODE is done running and OOBE is skipped

    return reboot_time, completed_time


def capture_bugreport(serial, f, cycle):
    logging(f, f"Capturing bugreport for iteration {cycle}")
    filename = f"bugreport_cycle_{cycle}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with open(filename, 'wb') as out:
        run(['adb', '-s', serial, 'bugreport'], stdout=out)
    logging(f, f"Bugreport saved to {filename}")


def run_reboot_stress(f, csv_writer):
    for cycle in range(1, REBOOT_TIMES + 1):
        logging(f, f"===== Cycle {cycle} START =====")
        cycle_start_time = time.time()

        if not run_factory_reset(SERIAL_NUMBER, f):
            logging(f, f"Factory reset command failed at cycle {cycle}")
            break

        reboot_time, completed_time = wait_for_boot_and_oobe(SERIAL_NUMBER, f)

        bugreport_flag = 'No'
        if reboot_time > MAX_REBOOT_TIME_SEC:
            logging(f, f"WARNING: Reboot time exceeded 5 minutes ({reboot_time:.2f} seconds)")
            capture_bugreport(SERIAL_NUMBER, f, cycle)
            bugreport_flag = 'Yes'

        # Write to CSV
        csv_writer.writerow([SERIAL_NUMBER, cycle, f"{reboot_time:.2f}", completed_time, bugreport_flag])

        cycle_end_time = time.time()
        cycle_total_time = (cycle_end_time - cycle_start_time) / 60
        logging(f, f"Cycle {cycle}'s Total Execution time is {cycle_total_time:.2f} minutes")
        logging(f, f"===== Cycle {cycle} COMPLETE =====\n")
        time.sleep(10)  # Optional delay before next cycle


def main():
    if len(sys.argv) != 3:
        print('Usage: python3 factory_reset_stress.py <SERIAL_NUMBER> <REBOOT_TIMES>')
        sys.exit(1)

    global SERIAL_NUMBER, REBOOT_TIMES
    SERIAL_NUMBER = sys.argv[1]
    REBOOT_TIMES = int(sys.argv[2])

    devices = run(['adb', 'devices'], capture_output=True, text=True).stdout
    if SERIAL_NUMBER not in devices:
        print(f"No device with serial {SERIAL_NUMBER} connected.")
        sys.exit(1)

    log_file_name = f"factory_reset_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    csv_file_name = f"factory_reset_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    with open(log_file_name, 'w') as log_file, open(csv_file_name, 'w', newline='') as csv_file:
        logging(log_file, f"Starting factory reset stress test on device {SERIAL_NUMBER}")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['Serial Number', 'Cycle', 'Reboot Duration (s)', 'Reboot Completed Time', 'Bugreport Triggered'])

        run_reboot_stress(log_file, csv_writer)

        logging(log_file, "Test completed.")
        print(f"\nCSV results saved to: {csv_file_name}")


if __name__ == '__main__':
    main()

