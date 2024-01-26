##  Quick script to send metric data to local Wavefront proxy with sample defined metric name from a specified source, 
## contiues sending random values until killed 
## 
##  Usage: python sendTestPoints.py --metric test-points --source test-source1 
##
## Graham O Neill
import time 
import argparse 
import socket 
import sys 
import random 
def parse_args(): 
    # Set-up for arguments 
    parser = argparse.ArgumentParser() 
    parser.add_argument( 
        "--metric", 
        "-m", 
        help="Metric name", 
        type=str, 
        required=True 
    ) 
    parser.add_argument( 
        "--source", "-s", help="Source name", type=str, required=True) 
    return parser.parse_args() 
def main(): 
    # Create a TCP/IP socket 
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
    # Connect the socket to the port where the server is listening for (only tested locally on wavefront proxy) 
    server_address = ('localhost', 2878) 
    print('connecting to %s port %s' % server_address) 
    s.connect(server_address) 
    s.settimeout(15) 
    try: 
        while True: 
            # Generate random metric value between 0 & 1000 
            random_value = random.randint(0, 1000) 
            # Append metric name random vale and source 
            metric =  ARGS.metric +" %s " %random_value + "source=%s \n" %ARGS.source 
            print('Sending the following metric, value and source name: \n') 
            print('%s' % metric) 
            s.send(metric) 
            # sleep 30 seconds & repeat 
            time.sleep(30) 
    finally: 
        print('closing socket') 
        s.close() 
if __name__ == "__main__": 
    ARGS = parse_args() 
    sys.exit(main())
