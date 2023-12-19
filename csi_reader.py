import os
import sys
import io
import struct
import ctypes
import dpkt
import numpy as np
import paramiko
import time
from csi_params import * 

_LIB = ctypes.CDLL(os.path.dirname(os.path.abspath(__file__)) +
                       '/unpack_float_py.so')
_C_UNPACK_FLOAT = _LIB.unpack_float_acphy
_C_UNPACK_FLOAT.argtypes = [
    ctypes.c_int,           # int nbits
    ctypes.c_int,           # int autoscale
    ctypes.c_int,           # int shft
    ctypes.c_int,           # int fmt
    ctypes.c_int,           # int nman
    ctypes.c_int,           # int nexp
    ctypes.c_int,           # int nfft
    ctypes.POINTER(ctypes.c_uint32), # uint32_t* H
    ctypes.POINTER(ctypes.c_uint32)  # uint32_t* Hout
]
_C_UNPACK_FLOAT.restype = None

def unpack_csi(payload, chip):
    """Unpacks a raw CSI packet.

    Args:
        payload: Raw packet data to unpack.
        chip: Monitor chip.

    Returns:
        Unpacked packet data as dict.
        'src_mac'  - Source MAC address of frame.
        'seq_num'  - Sequence numbe of frame.
        'core'     - Antenna number.
        'stream'   - Spatial stream.
        'chan_spec'- Channel spec.
        'chip_ver' - Chip version.
        'rssi'     - RSSI value.

    """
    unpacked_csi = {}

    if chip == '4366c0':
        header_fmt = '<I6cHHHHh'
        nfft = (len(payload)-struct.calcsize(header_fmt))//4        # metadata length

        fmt = header_fmt + str(nfft) + 'I'
        unpacked = struct.unpack(fmt, payload)

        # magic_num = unpacked[0]                                   # uint32, 0x11111111 
        unpacked_csi['src_mac'] = ':'.join(b.hex() for b in unpacked[1:7])    # uint8[6]           
        unpacked_csi['seq_num'] = unpacked[7]                       # uint16             
        unpacked_csi['core'] = ((unpacked[8] >> 8) & 0x7)           # uint16
        unpacked_csi['stream'] = ((unpacked[8] >> 11) & 0x7)        # uint16
        unpacked_csi['chan_spec'] = unpacked[9]                     # uint16             
        unpacked_csi['chip_ver'] = unpacked[10]                     # uint16             
        unpacked_csi['rssi'] = unpacked[11]                         # int16

        data = unpacked[12:]                                        # uint32[BW*3.2]
        H = (ctypes.c_uint32*len(data))(*data)
        Hout = (ctypes.c_uint32*(2*len(data)))()
        _C_UNPACK_FLOAT(10, 1, 0, 1, 12, 6, len(data), H, Hout)

        # Scale CSI by RSSI factor.
        data = np.fft.fftshift(np.frombuffer(Hout, dtype=np.int32).astype(np.float32).view(np.complex64))
        data_subc = data[data_bins[nfft]]
        # scale_factor = np.sqrt((unpacked_csi["rssi"]+100)/np.sum(np.vdot(data_subc,data_subc)))
        scale_factor = np.power(10, unpacked_csi['rssi']/20)/np.sqrt(np.sum(np.vdot(data_subc,data_subc)))*1000 # times 1000 to scale it into roughly 0~3

        unpacked_csi['data'] = data*scale_factor

    elif chip == '4358':
        header_fmt = '<I6cHHHH'
        nfft = (len(payload)-struct.calcsize(header_fmt))//4        # metadata length

        fmt = header_fmt + str(nfft) + 'I'
        unpacked = struct.unpack(fmt, payload)

        # magic_num = unpacked[0]                                   # uint32, 0x11111111 
        unpacked_csi['src_mac'] = ':'.join(b.hex() for b in unpacked[1:7])     # uint8[6]           
        unpacked_csi['seq_num'] = unpacked[7]                       # uint16             
        unpacked_csi['core'] = ((unpacked[8] >> 8) & 0x7)           # uint16
        unpacked_csi['stream'] = ((unpacked[8] >> 11) & 0x7)        # uint16
        unpacked_csi['chan_spec'] = unpacked[9]                     # uint16             
        unpacked_csi['chip_ver'] = unpacked[10]                     # uint16             

        data = unpacked[11:]                                        # uint32[BW*3.2]
        H = (ctypes.c_uint32*len(data))(*data)
        Hout = (ctypes.c_uint32*(2*len(data)))()
        _C_UNPACK_FLOAT(10, 1, 0, 1, 9, 5, len(data), H, Hout)

        unpacked_csi['data'] = \
            np.fft.fftshift(np.frombuffer(Hout, dtype=np.int32).astype(np.float32).view(np.complex64))

    elif chip == '43455c0' or chip == '4339':
        header_fmt = '<I6cHHHH'
        nfft = (len(payload)-struct.calcsize(header_fmt))//4        # metadata length

        fmt = header_fmt + str(2*nfft) + 'h'
        unpacked = struct.unpack(fmt, payload)

        # magic_num = unpacked[0]                                   # uint32, 0x11111111 
        unpacked_csi['src_mac'] = ':'.join(b.hex() for b in unpacked[1:7])     # uint8[6]           
        unpacked_csi['seq_num'] = unpacked[7]                       # uint16             
        unpacked_csi['core'] = ((unpacked[8] >> 8) & 0x7)           # uint16
        unpacked_csi['stream'] = ((unpacked[8] >> 11) & 0x7)        # uint16
        unpacked_csi['chan_spec'] = unpacked[9]                     # uint16             
        unpacked_csi['chip_ver'] = unpacked[10]                     # uint16          
        data = unpacked[11:]                                        # uint16[2*BW*3.2]     

        unpacked_csi['data'] = \
            np.fft.fftshift(np.array(data,dtype=np.int16).astype(np.float32).view(np.complex64))

    else:
        raise ValueError('Invalid chip.')

    return unpacked_csi

class CSIMonitor:
    def __init__(self, monitor_ip, monitor_user, monitor_pwd,
                 chip, chan_spec, core_mask, stream_mask, clients):
        """Interface to Nexmon CSI collection device.

        Args:
            monitor_ip: IP address of monitor. 
            monitor_user: SSH username of monitor.
            monitor_pwd: SSH password of monitor.
            chip: Chip of monitor.
            chan_spec: Chanspec (channel + bandwidth).
            core_mask: Cores (antennas).
            stream_mask: Spatial streams.
            clients: List of client MAC addresses to filter by.
        """

        self.monitor_ip   = monitor_ip
        self.monitor_user = monitor_user
        self.monitor_pwd  = monitor_pwd
        self.chip         = chip
        self.chan_spec    = chan_spec
        self.core_mask    = core_mask
        self.cores        = get_bitmask_positions(self.core_mask)
        self.stream_mask  = stream_mask
        self.streams      = get_bitmask_positions(self.stream_mask)
        self.clients      = clients
        self.csi_params   = get_csi_params(chan_spec, core_mask, stream_mask, clients)

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(monitor_ip, username=monitor_user, password=monitor_pwd)

        if self.chip == '43455c0':
            self.ssh.exec_command('modprobe -r brcmfmac')
            time.sleep(1)
            self.ssh.exec_command('modprobe brcmfmac')
            time.sleep(1)
            self.ssh.exec_command('ifconfig wlan0 up')
            self.ssh.exec_command('nexutil -Iwlan0 -s500 -b -l34 -v' + self.csi_params)
            self.ssh.exec_command('nexutil -m1')

        elif chip == '4358':
            self.ssh.exec_command('ifconfig wlan0 up')
            self.ssh.exec_command('nexutil -Iwlan0 -s500 -b -l34 -v' + self.csi_params)
            self.ssh.exec_command('nexutil -m1')

        elif chip == '4366c0':
            self.ssh.exec_command('/sbin/rmmod dhd.ko')
            time.sleep(1)
            print('rmmod dhd.ko')
            self.ssh.exec_command('/sbin/insmod /jffs/dhd.ko')
            time.sleep(3)
            print('insmod dhd.ko')
            self.ssh.exec_command('wl -i eth6 up')
            self.ssh.exec_command('wl -i eth6 radio on')
            self.ssh.exec_command('wl -i eth6 country US')
            self.ssh.exec_command('ifconfig eth6 up')
            time.sleep(3)
            print('eth6 up')
            self.ssh.exec_command('/jffs/nexutil -Ieth6 -s500 -b -l34 -v' + self.csi_params)
            time.sleep(1)
            print('nexutil configured')
            self.ssh.exec_command('/usr/sbin/wl -i eth6 monitor 1')

            _,stdout,_ = self.ssh.exec_command('/jffs/nexutil -Ieth6 -k')
            print('/jffs/nexutil -Ieth6 -k', stdout.read())
            _,stdout,_ = self.ssh.exec_command('/jffs/nexutil -Ieth6 -m')
            print('/jffs/nexutil -Ieth6 -m', stdout.read())

        else:
            raise ValueError('Invalid chip.')
    
    def dump_pcap(self, n_frames):
        """Retrieves n_frames of CSI data.

        Args:
            n_frames: Number of CSI frames to extract.

        Returns:
            n_frames of raw CSI data in .pcap format.
        """

        if self.chip == '4366c0':
            cmd = '/jffs/tcpdump -i eth6 dst port 5500 -U -w - -c '\
                + str(n_frames) \
                + ' 2>/dev/null'
        elif self.chip == '43455c0' or self.chip == '4358' or self.chip == '4339':
            cmd = 'tcpdump -i wlan0 dst port 5500 -U -w - -c '\
                + str(n_frames) \
                + ' 2>/dev/null'
        else:
            raise ValueError('Invalid chip.')

        _,stdout,_ = self.ssh.exec_command(cmd)
        pcap = stdout.read()

        return pcap

    def dump_csi(self, n_samples):

        # Initialize counters.
        count = np.zeros((len(self.clients),len(self.cores),len(self.streams)))
        
        # Initialize empty lists to hold result. 
        csi = [[[[] for _ in self.streams] for _ in self.cores] for _ in self.clients]

        if self.chip == '4366c0':
            cmd = '/jffs/tcpdump -i eth6 dst port 5500 -U -w - 2>/dev/null'
        else:
            cmd = 'tcpdump -i wlan0 dst port 5500 -U -w - 2>/dev/null'

        _, stdout, _ = self.ssh.exec_command(cmd)
        _ = stdout.read(24) # global pcap header

        while not np.all(count >= n_samples):
            packet_header = stdout.read(16)
            pkt_len = int.from_bytes(packet_header[12:16], 'little')
            packet = stdout.read(pkt_len)
            payload = packet[42:]
            unpacked_csi = unpack_csi(payload,self.chip)

            client_idx = self.clients.index(unpacked_csi['src_mac'])
            core_idx = self.cores.index(unpacked_csi['core'])
            stream_idx = self.streams.index(unpacked_csi['stream'])

            if count[client_idx,core_idx,stream_idx] >= n_samples:
                continue

            count[client_idx,core_idx,stream_idx] += 1
            csi[client_idx][core_idx][stream_idx].append(unpacked_csi['data'])

        stdout.channel.close()
        self.ssh.exec_command('killall tcpdump')

        csi = np.array(csi)            
        return csi

    def monitor_csi(self, queue):
        """Start CSI collection on device, feeding CSI to queue.

        Args:
            queue: Multiprocessing queue to feed CSI to.
        """
        if self.chip == '4366c0':
            cmd = '/jffs/tcpdump -i eth6 dst port 5500 -U -w - 2>/dev/null'
        else:
            cmd = 'tcpdump -i wlan0 dst port 5500 -U -w - 2>/dev/null'

        _,stdout,_ = self.ssh.exec_command(cmd)
        _ = stdout.read(24) # global pcap header

        while True:
            if not queue.full():
                packet_header = stdout.read(16)
                pkt_len = int.from_bytes(packet_header[12:16], 'little')
                packet = stdout.read(pkt_len)
                payload = packet[42:]
                unpacked_csi = unpack_csi(payload,self.chip)
                queue.put(unpacked_csi)
    
    def __del__(self):
        if self.chip == '4366c0':
            self.ssh.exec_command('/jffs/nexutil -Ieth6 -m0')
            self.ssh.close()
        else:
            self.ssh.exec_command('nexutil -m0')
            self.ssh.close()
        
