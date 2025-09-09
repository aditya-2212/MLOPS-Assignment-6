import time
import subprocess
import re
import logging
from prometheus_client import start_http_server, Gauge

# Configure logging to display messages with the time, log level, and message.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Prometheus Gauges for disk I/O statistics with device labels.
# The 'device' label allows tracking metrics for each individual disk device.
io_read_rate = Gauge('io_read_rate', 'I/O read rate in KB/s', ['device'])
io_write_rate = Gauge('io_write_rate', 'I/O write rate in KB/s', ['device'])
io_tps = Gauge('io_tps', 'I/O transactions per second', ['device'])
io_read_bytes = Gauge('io_read_bytes', 'I/O read bytes', ['device'])
io_write_bytes = Gauge('io_write_bytes', 'I/O write bytes', ['device'])

# Initialize a Prometheus Gauge for CPU statistics.
# The 'mode' label distinguishes between different CPU usage types.
cpu_avg_percent = Gauge('cpu_avg_percent', 'CPU average percentage', ['mode'])

def collect_iostat_metrics():
    """
    Collect the required disk I/O and CPU statistics using the iostat command.
    This function runs the iostat command, parses the output to extract:
    - CPU usage values (%user, %nice, %system, %iowait, %steal, %idle)
    - Disk I/O statistics (transactions per second, KB read per second, KB write per second)
    Then it updates the corresponding Prometheus metrics.
    """
    try:
        # Run the iostat command and capture its output.
        result = subprocess.run(['iostat'],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True)
        iostat_output = result.stdout
        logger.debug(f"iostat output: {iostat_output}")

        # Split the output into separate lines for parsing.
        lines = iostat_output.splitlines()

        # Loop through the lines to find CPU statistics.
        # Look for a line containing '%user' which indicates the header for CPU metrics.
        for i, line in enumerate(lines):
            if '%user' in line and i+1 < len(lines):
                # The line after the header contains the CPU usage values.
                cpu_vals = lines[i+1].split()
                if len(cpu_vals) >= 6:
                    # Set each CPU mode metric accordingly.
                    cpu_avg_percent.labels('user').set(float(cpu_vals[0]))
                    cpu_avg_percent.labels('nice').set(float(cpu_vals[1]))
                    cpu_avg_percent.labels('system').set(float(cpu_vals[2]))
                    cpu_avg_percent.labels('iowait').set(float(cpu_vals[3]))
                    cpu_avg_percent.labels('steal').set(float(cpu_vals[4]))
                    cpu_avg_percent.labels('idle').set(float(cpu_vals[5]))
                    logger.info("Updated CPU metrics")
                break

        # Initialize a flag to start parsing the device statistics section.
        device_section = False
        for line in lines:
            # Check for the header indicating the start of device statistics.
            if 'Device' in line:
                device_section = True
                continue  # Skip the header line

            # If we are in the device section and the line is not empty.
            if device_section and line.strip():
                parts = line.split()
                if len(parts) >= 4:
                    # Extract the device name and its corresponding statistics.
                    device = parts[0]
                    tps = float(parts[1])         # Transactions per second
                    kb_read_sec = float(parts[2])   # Kilobytes read per second
                    kb_write_sec = float(parts[3])  # Kilobytes written per second

                    # Update Prometheus metrics for the device.
                    io_tps.labels(device).set(tps)
                    io_read_rate.labels(device).set(kb_read_sec)
                    io_write_rate.labels(device).set(kb_write_sec)
                    io_read_bytes.labels(device).set(kb_read_sec * 1024)   # Convert to bytes
                    io_write_bytes.labels(device).set(kb_write_sec * 1024)   # Convert to bytes

                    logger.info(f"Updated I/O metrics for device {device}")

        # Return True if metrics collection succeeded.
        return True
    except Exception as e:
        # Log any errors that occur during the metrics collection.
        logger.error(f"Error collecting iostat metrics: {e}")
        return False
    

# Dictionary to store Prometheus Gauge objects for each meminfo metric.
meminfo_gauges = {}

def collect_meminfo_metrics():
    """
    Collect memory information from the /proc/meminfo file.
    
    /proc/meminfo contains several lines with key: value pairs,
    where the values are usually given in kilobytes. This function:
    
    1. Opens /proc/meminfo and reads its contents.
    2. Processes each line to extract a key and its numeric value.
    3. Converts the key to a standardized metric name by converting it to lowercase
       and prepending 'meminfo_'.
    4. Creates a new Prometheus Gauge for the metric if it does not exist.
    5. Updates the gauge with the extracted numeric value.
    
    Returns:
        True if metrics were updated successfully, otherwise False.
    """
    try:
        # Open /proc/meminfo in read mode.
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
        
        # Process each line of the file.
        for line in lines:
            # Check if the line contains a colon (:) to separate key and value.
            if ':' in line:
                # Split the line into a key and the rest of the line.
                key, value_str = line.split(':', 1)
                key = key.strip()  # Remove any extra whitespace from the key
                
                # Use a regular expression to extract the first sequence of digits from the value string.
                value_match = re.search(r'(\d+)', value_str.strip())
                if value_match:
                    # Convert the extracted number to an integer.
                    # The value in /proc/meminfo is usually in kilobytes.
                    value_kb = int(value_match.group(1))

                    # Convert kilobyte to bytes
                    value_bytes = value_kb * 1024 
                    
                    # Create a standardized metric name.
                    # Example: "MemTotal" becomes "meminfo_memtotal_bytes".
                    # To solve issues with special characters like barckets, we replace them with underscores.
                    sanitized_key = re.sub(r'[^a-zA-Z0-9_]', '_', key.lower())
                    metric_name = f"meminfo_{sanitized_key}_bytes"
                    
                    # Check if a Gauge for this metric already exists; if not, create one.
                    if metric_name not in meminfo_gauges:
                        meminfo_gauges[metric_name] = Gauge(
                            metric_name, 
                            f'Memory information: {key}'
                        )
                    
                    # Update the gauge with the current value in bytes.
                    meminfo_gauges[metric_name].set(value_bytes)
        
        # Log a message indicating that memory metrics have been updated.
        logger.info("Updated memory metrics")
        return True
    except Exception as e:
        # Log an error if something goes wrong during metric collection.
        logger.error(f"Error collecting memory metrics: {e}")
        return False

# Example main loop to start the HTTP server and periodically collect metrics.
if __name__ == '__main__':
    # Start the Prometheus metrics HTTP server on port 18000.
    start_http_server(18000)
    logger.info("Prometheus metrics server started on port 18000")

    # Continuously collect metrics at a fixed interval.
    while True:
        collect_iostat_metrics() # Collect Task 1 (I/O) metrics
        collect_meminfo_metrics()  # Collect Task 2 (Memory) metrics
        # Scrape interval of 1 second between metric collections. Can be adjusted as needed.
        time.sleep(1)
