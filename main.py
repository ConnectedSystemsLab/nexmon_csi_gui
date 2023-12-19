#!/usr/bin/env python3

import sys
import time
from csi_reader import * 
from csi_params import *
from multiprocessing import Process, Queue
from PyQt5 import QtWidgets, QtCore
from pyqtgraph import PlotWidget, plot
import pyqtgraph as pg
from absl import app
from absl import flags
import numpy as np

FLAGS = flags.FLAGS
flags.DEFINE_string('monitor_ip', '192.168.10.1', 'IP address of monitor to read packets from.')
flags.DEFINE_string('monitor_user', 'admin', 'Username for monitor.')
flags.DEFINE_string('monitor_pwd',  'admin', 'Password for monitor.')
flags.DEFINE_enum('chip', '4366c0', ['4358', '43455c0', '4366c0'], 'Wifi card. Possible options are 4358 for Nexus 6P, 43455c0 for Raspberry Pi 4, 4366c0 for ASUS RT-AC86U')
flags.DEFINE_string('chan_spec', '40/20', 'Channel specification.')
flags.DEFINE_integer('core_mask', 15, 'Bitmask for cores to use.', lower_bound=0, upper_bound=15)
flags.DEFINE_integer('stream_mask', 15, 'Bitmask for streams to use.', lower_bound=0, upper_bound=15)
flags.DEFINE_multi_string('clients', None, 'List of client MAC addresses.')
flags.DEFINE_integer('queue_size', 100, 'Max number of CSI to buffer', lower_bound=0)

flags.mark_flag_as_required('clients')

class MainWindow(QtWidgets.QMainWindow):

    def __init__(self, queue, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        # Process flags.
        self.cores        = get_bitmask_positions(FLAGS.core_mask)
        self.streams      = get_bitmask_positions(FLAGS.stream_mask)
        self.n_subc       = get_subc(FLAGS.chan_spec)
        self.csi_antenna  = [np.ones(self.n_subc, dtype=complex) for _ in enumerate(self.cores)]
        self.rssi_antenna = [[] for _ in enumerate(self.cores)]

        # Data feed.
        self.queue = queue 

        # Subplots.
        self.canvas = pg.GraphicsLayoutWidget()
        self.setCentralWidget(self.canvas)

        # CSI Abs subplots.
        self.csi_plots = [[self.canvas.addPlot(row=i,col=2*j) 
                           for j,_ in enumerate(self.streams)] 
                           for i,_ in enumerate(self.cores)]

        # CSI Phase subplots.
        self.csi_phase_plots = [[self.canvas.addPlot(row=i, col=2*j+1) 
                                 for j, _ in enumerate(self.streams)] 
                                 for i, _ in enumerate(self.cores)]
        # RSSI subplots.
        self.rssi_plots = [self.canvas.addPlot(row=i,col=2*len(self.streams)) 
                           for i,_ in enumerate(self.cores)]

        # Fill subplots.

        # Abs plots
        self.canvas.setBackground('w')
        pen = pg.mkPen(color=(255, 0, 0), width=3)
        x = subcarriers[self.n_subc][data_bins[self.n_subc]]
        y = [0 for _ in range(len(x))] 
        self.csi_lines_abs = [[self.csi_plots[i][j].plot(x, y, pen=pen) 
                               for j, _ in enumerate(self.streams)] 
                               for i, _ in enumerate(self.cores)]
        [self.csi_plots[i][j].setXRange(min(x),max(x)) 
                               for i,_ in enumerate(self.cores) 
                               for j,_ in enumerate(self.streams)]
        [self.csi_plots[i][j].setYRange(0, 3) 
                               for i,_ in enumerate(self.cores) 
                               for j,_ in enumerate(self.streams)]
        [self.csi_plots[i][j].setTitle(f"[Abs] Core {core}, Stream {stream}", **{'size': '22pt'}) 
                               for i,core in enumerate(self.cores) 
                               for j,stream in enumerate(self.streams)]

        # RSSI plots
        pen = pg.mkPen(color=(0, 255, 0), width=3)
        self.rssi = [[-100 for _ in range(100)] for _ in self.cores]
        self.rssi_lines = [self.rssi_plots[i].plot(self.rssi[i],pen=pen) 
                           for i,_ in enumerate(self.cores)]
        [self.rssi_plots[i].setXRange(0,100)  for i,_ in enumerate(self.cores)]
        [self.rssi_plots[i].setYRange(-100,0) for i,_ in enumerate(self.cores)]
        [self.rssi_plots[i].setTitle(f"[RSSI] Core {i}", **{'size': '22pt'}) 
                for i,_ in enumerate(self.cores)]

        # Phase plots
        pen = pg.mkPen(color=(0, 0, 255), width=3)
        x = subcarriers[self.n_subc][data_bins[self.n_subc]]
        y = [0 for _ in range(len(x))]
        self.csi_lines_phase = [[self.csi_phase_plots[i][j].plot(x, y, pen=pen) 
                                 for j, _ in enumerate(self.streams)] 
                                 for i, _ in enumerate(self.cores)]
        [self.csi_phase_plots[i][j].setXRange(min(x), max(x)) 
                for i, _ in enumerate(self.cores) 
                for j, _ in enumerate(self.streams)]
        [self.csi_phase_plots[i][j].setYRange(-20, 20) 
                for i, _ in enumerate(self.cores) 
                for j, _ in enumerate(self.streams)]
        [self.csi_phase_plots[i][j].setTitle(f"[Phase] Core {core}, Stream {stream}", **{'size': '22pt'}) 
                for i, core in enumerate(self.cores) 
                for j, stream in enumerate(self.streams)]

        # Set timer.
        self.timer = QtCore.QTimer()
        self.timer.setInterval(1)
        self.timer.timeout.connect(self.update_plot_data)
        self.timer.start()

        self.fps = None
        self.lastTime = time.perf_counter()


    def update_plot_data(self):

        # Dequeue new CSI
        if self.queue.empty():
            return
        elif self.queue.full():
            print('Warning: Queue is full.')
        new_csi = self.queue.get()

        # Find core and stream idx.
        core_idx   = self.cores.index(new_csi["core"])
        stream_idx = self.streams.index(new_csi["stream"])

        # Get CSI data.
        n_subc   = len(new_csi["data"])
        csi_data = new_csi["data"][data_bins[n_subc]]
        rssi     = new_csi["rssi"]

        # Store per-core CSI and RSSI.
        self.csi_antenna[core_idx]  = csi_data
        self.rssi_antenna[core_idx] = rssi 

        # Get scaled CSI.
        x = subcarriers[n_subc][data_bins[n_subc]]
        y = np.abs(csi_data)

        # Update CSI Abs.
        self.csi_lines_abs[core_idx][stream_idx].setData(x, y)

        # Update RSSI.
        self.rssi[core_idx] = self.rssi[core_idx][1:] + [new_csi["rssi"]]
        self.rssi_lines[core_idx].setData(self.rssi[core_idx])

        # Update CSI Phase Ratio.
        y = np.unwrap(np.angle(csi_data/self.csi_antenna[0]))
        self.csi_lines_phase[core_idx][stream_idx].setData(x, y)

        # Update FPS.
        self.fps = 1.0/(time.perf_counter() - self.lastTime)
        self.lastTime = time.perf_counter()

        self.setWindowTitle(f"FPS: {self.fps}")

def listen_csi(queue):
    monitor = CSIMonitor(FLAGS.monitor_ip, 
                         FLAGS.monitor_user, 
                         FLAGS.monitor_pwd, 
                         FLAGS.chip,
                         FLAGS.chan_spec, 
                         FLAGS.core_mask, 
                         FLAGS.stream_mask, 
                         FLAGS.clients)
    monitor.monitor_csi(queue)

def main(_):
    try:
        # Init queue to store incoming data.
        queue = Queue(FLAGS.queue_size)

        # Init the GUI.
        gui_thread = QtWidgets.QApplication(sys.argv)
        window = MainWindow(queue)
        window.resize(900, 600)
        window.show()

        # Start listening for CSI and adding it to the queue.
        monitor_thread = Process(target=listen_csi, args=(queue,))
        monitor_thread.start()

        # Run the GUI on current thread.
        gui_thread.exec_()
    finally:
        monitor_thread.join()

if __name__ == '__main__':
    app.run(main)
