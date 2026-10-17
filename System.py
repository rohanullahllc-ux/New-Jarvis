import psutil
import math
import speech_recognition as sr
import platform
import socket
import requests
from MainCode import Speak

def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def system_stats():
    cpu_stats = str(psutil.cpu_percent())
    battery_percent = psutil.sensors_battery()
    memory_in_use = convert_size(psutil.virtual_memory().used)
    total_memory = convert_size(psutil.virtual_memory().total)
    final_res = f"Currently {cpu_stats} percent of CPU, {memory_in_use} of RAM out of total {total_memory} is being used."
    Speak(final_res)


def username():
    username = psutil.users()
    for user_name in username:
        first_name = user_name[0]
        Speak(f"Sir, this computer is signed to {first_name} as a username.")


def VirtualRam():
    psutil.cpu_percent()
    psutil.virtual_memory()
    dict(psutil.virtual_memory()._asdict())
    Speak(f"Sir you have used {psutil.virtual_memory().percent} percentage of RAM")


def AvailableRam():
    psutil.cpu_percent()
    psutil.virtual_memory()
    dict(psutil.virtual_memory()._asdict())
    Speak(f"Sir your available memory is: {int(psutil.virtual_memory().available * 100 / psutil.virtual_memory().total)} percentage.")


def SysInfo():
    uname = platform.uname()
    Speak("Your system information...")
    Speak(f"System: {uname.system}")
    Speak(f"Node Name: {uname.node}")
    Speak(f"Release: {uname.release}")
    Speak(f"Version: {uname.version}")
    Speak(f"Machine: {uname.machine}")
    Speak(f"Processor: {uname.processor}")


def CpuInfo():
    Speak("Your CPU information...")
    Speak(f"Physical Cores:{psutil.cpu_count(logical=False)}")
    Speak(f"Total cores:{psutil.cpu_count(logical=True)}")
    Spufreq = psutil.cpu_freq()
    Speak(f"Maximum Frequency: {Spufreq.max:.2f}Mhz")
    Speak(f"Minimum Frequency: {Spufreq.min:.2f}Mhz")
    Speak(f"Current Frequency: {Spufreq.current:.2f}Mhz")
    Speak("CPU Usage Per Cores:")
    for i, percentage in enumerate(psutil.cpu_percent(percpu=True, interval=1)):
        Speak(f"Core {i}: {percentage}%")
    Speak(f"Total CPU Usage: {psutil.cpu_percent()}%")


def DiskInfo():
    def get_size(bytes, suffix="B"):
        factor = 1024
        for unit in ["", "K", "M", "G", "T", "P"]:
            if bytes < factor:
                return f"{bytes:.2f}{unit}{suffix}"
            bytes /= factor
        return bytes

    Speak("Sir your Disk Information:")
    Speak("Partitions and Usage:")
    partitions = psutil.disk_partitions()
    for partition in partitions:
        Speak(f" Device: {partition.device}")
        Speak(f"  Mountpoint: {partition.mountpoint}")
        Speak(f"  File system type: {partition.fstype}")
        try:
            partition_usage = psutil.disk_usage(partition.mountpoint)
        except PermissionError:
            continue
        Speak(f"  Total Size: {get_size(partition_usage.total)}")
        Speak(f"  Used: {get_size(partition_usage.used)}")
        Speak(f"  Free: {get_size(partition_usage.free)}")
        Speak(f"  Percentage: {partition_usage.percent}%")
                # get IO statistics since boot
    disk_io = psutil.disk_io_counters()
    Speak(f"Total read: {get_size(disk_io.read_bytes)}")
    Speak(f"Total write: {get_size(disk_io.write_bytes)}")


def MemoryInfo():
    def get_size(bytes, suffix="B"):
        factor = 1024
        for unit in ["", "K", "M", "G", "T", "P"]:
            if bytes < factor:
                return f"{bytes:.2f}{unit}{suffix}"
            bytes /= factor
        return bytes

    Speak("Sir your memory information:")
    # get the memory details
    svmem = psutil.virtual_memory()
    Speak(f"Total: {get_size(svmem.total)}")
    Speak(f"Available: {get_size(svmem.available)}")
    Speak(f"Used: {get_size(svmem.used)}")
    Speak(f"Percentage: {svmem.percent}%")
    Speak("Swap Memory")
    # get the swap memory details (if exists)
    swap = psutil.swap_memory()
    Speak(f"Total: {get_size(swap.total)}")
    Speak(f"Free: {get_size(swap.free)}")
    Speak(f"Used: {get_size(swap.used)}")
    Speak(f"Percentage: {swap.percent}%")


def check_int():
    IPaddress = socket. gethostbyname(socket. gethostname())
    if IPaddress == "127.0.0.1":
        Speak('no internet connection')
    else:
        Speak("Connected, with the IP address: " + IPaddress)


def IPAddress():
    url = "https://api.ipify.org"
    req = requests.get(url)
    Data = req.text
    Speak(f"Your current ip address is {Data}")

