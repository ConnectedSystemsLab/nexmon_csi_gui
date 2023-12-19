import numpy as np
import subprocess
import os

# 20Mhz -> n_fft = 64
# 40Mhz -> n_fft = 128
# 80Mhz -> n_fft = 256
def _subcarriers(n_fft):
    return np.array([x for x in range(-(n_fft//2),(n_fft//2))])

subcarriers = {
    64  : _subcarriers(64),
    128 : _subcarriers(128),
    256 : _subcarriers(256),
}


guard_bins = {
    64  :  np.array([x+32  for x in [-32,-31,-30,-29,-28,-27,0,27,28,29,30,31]]),
    128 :  np.array([x+64  for x in [-64,-63,-62,-61,-60,-59,-1,0,1,59,60,61,62,63]]),
    256 :  np.array([x+128 for x in [-128,-127,-126,-125,-124,-123,-1,0,1,123,124,125,126,127]]),
}

pilot_bins = {
    64  : np.array([x+32  for x in [-21,-7,7,21]]),
    128 : np.array([x+64  for x in [-53,-25,-11,11,25,53]]),
    256 : np.array([x+128 for x in [-103,-75,-39,-11,11,39,75,103]]),
}

data_bins = {
    64  : np.array([x for x in range(64) 
                    if x not in guard_bins[64] and x not in pilot_bins[64]]),
    128 : np.array([x for x in range(128) 
                    if x not in guard_bins[128] and x not in pilot_bins[128]]),
    256 : np.array([x for x in range(256) 
                    if x not in guard_bins[256] and x not in pilot_bins[256]]),
}

def get_bitmask_positions(bitmask):
    """Return list of enabled bitmask indices in sorted order.

    Args:
        bitmask: Bitmask (0-15)

    Returns:
        Sorted list of indices.
    """

    return [i for i in range(4) if bitmask & (1 << i) > 0]

def get_subc(chan_spec):
    """Returns number of subcarriers in a channel spec.

    Args:
        chan_spec: Channel specification.

    Returns:
        Number of subcarriers.
    """
    _, bw = chan_spec.split('/')
    if bw == "20":
        return 64
    elif bw == "40":
        return 128
    elif bw == "80":
        return 256
    else:
        raise ValueError('Invalid channel.')

def get_csi_params(chan_spec, core_mask, stream_mask, clients):
    """Get CSI parameter string from makecsiparams.

    Args:
        chan_spec: Channel specification.
        core_mask: Bitmask for which cores to use (0-15).
        stream_mask: Bitmask for which streams to use  (0-15).
        clients: List of client MAC addresses.

    Returns:
        CSI parameter string from makecsiparams.
    """
    path = os.path.dirname(os.path.abspath(__file__)) + '/makecsiparams' 
    args = []
    if chan_spec:
        args.append(f"-c{chan_spec}")
    if core_mask:
        args.append(f"-C{core_mask}")
    if stream_mask:
        args.append(f"-N{stream_mask}")
    if clients:
        clients = ','.join(clients)
        args.append(f"-m{clients}")
    out = subprocess.run([path] + args, stdout=subprocess.PIPE) 
    return out.stdout.decode('utf-8')[:-1]
