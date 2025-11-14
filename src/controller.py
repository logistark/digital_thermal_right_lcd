import numpy as np
from metrics import Metrics
from config import leds_indexes, NUMBER_OF_LEDS, leds_indexes_small, display_modes, display_modes_small
from utils import interpolate_color, get_random_color
import hid
import time
import datetime 
import json
import os
import sys


# Digit mask for 7-segment displays
# Format: [top, top-right, bottom-right, bottom, bottom-left, top-left, middle]
digit_mask = np.array(
    [
        [1, 1, 1, 0, 1, 1, 1],  # 0
        [0, 0, 1, 0, 0, 0, 1],  # 1
        [0, 1, 1, 1, 1, 1, 0],  # 2
        [0, 1, 1, 1, 0, 1, 1],  # 3
        [1, 0, 1, 1, 0, 0, 1],  # 4
        [1, 1, 0, 1, 0, 1, 1],  # 5
        [1, 1, 0, 1, 1, 1, 1],  # 6
        [0, 1, 1, 0, 0, 0, 1],  # 7
        [1, 1, 1, 1, 1, 1, 1],  # 8
        [1, 1, 1, 1, 0, 1, 1],  # 9
        [0, 0, 0, 0, 0, 0, 0],  # nothing
    ]
)

letter_mask = {
    'H': [1, 0, 1, 1, 1, 0, 1],
}



def _number_to_array(number):
    if number>=10:
        return _number_to_array(int(number/10))+[number%10]
    else:
        return [number]

def get_number_array(temp, array_length=3, fill_value=-1):
    if temp<0:
        return [fill_value]*array_length
    else:
        narray = _number_to_array(temp)
        if (len(narray)!=array_length):
            if(len(narray)<array_length):
                narray = np.concatenate([[fill_value]*(array_length-len(narray)),narray])
            else:
                narray = narray[1:]
        return narray

class Controller:
    def __init__(self, config_path=None):
        self.temp_unit = {"cpu": "celsius", "gpu": "celsius"}
        self.metrics = Metrics()
        self.VENDOR_ID = 0x0416   
        self.PRODUCT_ID = 0x8001 
        self.dev = self.get_device()
        self.HEADER = 'dadbdcdd000000000000000000000000fc0000ff'
        self.leds = np.array([0] * NUMBER_OF_LEDS)
        self.leds_indexes = leds_indexes
        # Configurable config path
        if config_path is None:
            self.config_path = os.environ.get('DIGITAL_LCD_CONFIG', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json'))
        else:
            self.config_path = config_path
        self.cpt = 0  # For alternate_time cycling
        self.cycle_duration = 50
        self.display_mode = None
        self.colors = np.array(["ffe000"] * NUMBER_OF_LEDS)  # Will be set in update()
        self.update()

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return None

    def get_device(self):
        try:
            return hid.Device(self.VENDOR_ID, self.PRODUCT_ID)
        except Exception as e:
            print(f"Error initializing HID device: {e}")
            return None

    def set_leds(self, key, value):
        try:
            self.leds[self.leds_indexes[key]] = value
        except KeyError:
            print(f"Warning: Key {key} not found in leds_indexes.")

    def send_packets(self):
        message = "".join([self.colors[i] if self.leds[i] != 0 else "000000" for i in range(NUMBER_OF_LEDS)])
        packet0 = bytes.fromhex(self.HEADER+message[:128-len(self.HEADER)])
        self.dev.write(packet0)
        packets = message[88:]
        for i in range(0,4):
            packet = bytes.fromhex('00'+packets[i*128:(i+1)*128])
            self.dev.write(packet)

    def set_temp(self, temperature: int, device='cpu', unit="celsius"):
        if temperature < 1000:
            # Always use 3 digits with padding (fill with blank/10)
            digit_array = get_number_array(temperature, array_length=3, fill_value=10)
            leds = digit_mask[digit_array].flatten()
            # GPU: Try no transformation - LEDs already in reverse order should compensate
            # (keeping for testing - no transformation applied)
            self.set_leds(device + '_temp', leds)
            if unit == "celsius":
                self.set_leds(device + '_celsius', 1)
            elif unit == "fahrenheit":
                self.set_leds(device + '_fahrenheit', 1)
        else:
            raise Exception("The numbers displayed on the temperature LCD must be less than 1000")

    def set_usage(self, usage : int, device='cpu'):
        if usage<200:
            # Use 2 digits for the main number
            digit_array = get_number_array(usage, array_length=2, fill_value=10)
            # Prepend 2 LEDs for the "1" digit when usage >= 100
            leds = np.concatenate(([int(usage>=100)]*2, digit_mask[digit_array].flatten()))
            # GPU: Try no transformation - LEDs already in reverse order should compensate
            # (keeping for testing - no transformation applied)
            self.set_leds(device+'_usage', leds)
            self.set_leds(device+'_percent_led', 1)
        else:
            raise Exception("The numbers displayed on the usage LCD must be less than 200")

    def display_metrics(self, devices=["cpu","gpu"]):
        self.temp_unit = {device: self.config.get(f"{device}_temperature_unit", "celsius")for device in ["cpu","gpu"]}
        metrics = self.metrics.get_metrics(temp_unit=self.temp_unit)
        for device in devices:
            self.set_leds(device+"_led", 1)
            self.set_temp(metrics[device+"_temp"], device=device, unit=self.temp_unit[device])
            self.set_usage(metrics[device+"_usage"], device=device)
            self.colors[self.leds_indexes[device]] = self.metrics_colors[self.leds_indexes[device]]

    def display_digit_test(self):
        """Test mode: cycle through sequences 111, 222, 333... 999 every 2 seconds"""
        import time
        test_digit = (int(time.time() / 2) % 9) + 1  # 1-9

        # Create sequence like 111, 222, 333, etc.
        test_number = test_digit * 111  # 111, 222, 333...

        # Show same sequence on all matrices for easy verification
        print(f"Showing sequence: {test_number}")

        if self.config.get("layout_mode") == "small":
            # Small layout: cycle through devices showing test number
            cycle = (int(time.time() / 4) % 4)  # 0-3, changes every 4 seconds
            devices = ["cpu", "gpu"]
            device = devices[cycle % 2]

            self.set_leds(device+"_led", 1)
            if cycle < 2:  # Show temperature
                self.set_leds('celsius', 1)
                digit_array = get_number_array(test_number, array_length=3, fill_value=10)
                self.set_leds('digit_frame', digit_mask[digit_array].flatten())
            else:  # Show usage
                self.set_leds('percent_led', 1)
                digit_array = get_number_array(test_number, array_length=3, fill_value=10)
                self.set_leds('digit_frame', digit_mask[digit_array].flatten())
            self.colors = self.metrics_colors
        else:
            # Big layout: show on both CPU and GPU simultaneously
            for device in ["cpu", "gpu"]:
                self.set_leds(device+"_led", 1)
                # Show test sequence on temperature (e.g., 111, 222, 333)
                self.set_temp(test_number, device=device, unit="celsius")
                # Show test digit on usage (e.g., 11, 22, 33)
                self.set_usage(test_digit * 11, device=device)
                self.colors[self.leds_indexes[device]] = self.metrics_colors[self.leds_indexes[device]]

    def display_time(self, device="cpu"):
        current_time = datetime.datetime.now()
        self.set_leds(device+'_temp', np.concatenate((digit_mask[get_number_array(current_time.hour, array_length=2, fill_value=0)].flatten(),letter_mask["H"])))
        self.set_leds(device+'_usage', np.concatenate(([0,0],digit_mask[get_number_array(current_time.minute, array_length=2, fill_value=0)].flatten())))
        self.colors[self.leds_indexes[device]] = self.time_colors[self.leds_indexes[device]]
    
    def display_time_with_seconds(self):
        current_time = datetime.datetime.now()
        self.set_leds('cpu_temp', np.concatenate((digit_mask[get_number_array(current_time.hour, array_length=2, fill_value=0)].flatten(),letter_mask["H"])))
        self.set_leds('gpu_usage', np.concatenate(([0,0],digit_mask[get_number_array(current_time.second, array_length=2, fill_value=0)].flatten())))
        self.set_leds('cpu_usage', np.concatenate(([0,0],digit_mask[get_number_array(current_time.minute, array_length=2, fill_value=0)].flatten())))
        self.colors = self.time_colors

    def display_temp_small(self, device='cpu'):
        unit = {device: self.config.get(f"{device}_temperature_unit", "celsius")for device in ["cpu","gpu"]}
        self.set_leds(unit[device], 1)
        self.set_leds(device+'_led', 1)
        current_temp = self.metrics.get_metrics(self.temp_unit)[f"{device}_temp"]
        self.colors = self.metrics_colors
        if current_temp is not None:
            # Use 3 digits with blank padding (10) for proper display (e.g., " 50" not "050")
            digit_array = get_number_array(current_temp, array_length=3, fill_value=10)
            self.set_leds('digit_frame', digit_mask[digit_array].flatten())
        else:
            print(f"Warning: {device} temperature not available.")
    
    def display_usage_small(self, device='cpu'):
        current_usage = self.metrics.get_metrics(self.temp_unit)[f"{device}_usage"]
        self.set_leds('percent_led', 1)
        self.set_leds(device+'_led', 1)
        self.colors = self.metrics_colors
        if current_usage is not None:
            # Use 3 digits with blank padding (10) for proper display (e.g., " 75" not "075", or "100")
            digit_array = get_number_array(current_usage, array_length=3, fill_value=10)
            self.set_leds('digit_frame', digit_mask[digit_array].flatten())
        else:
            print(f"Warning: {device} usage not available.")

    def get_config_colors(self, config, key="metrics"):
        conf_colors = config.get(key, {}).get('colors', ["ffe000"] * NUMBER_OF_LEDS)
        if len(conf_colors) != NUMBER_OF_LEDS:
            print(f"Warning: config {key} colors length mismatch, using default colors.")
            colors = ["ff0000"] * NUMBER_OF_LEDS
        else:
            colors = []
            for color in conf_colors:
                if color.lower()=="random":
                    colors.append(get_random_color())
                elif "-" in color:
                    split_color = color.split("-")
                    if len(split_color) == 3:
                        start_color, end_color, key = split_color
                        current_time = datetime.datetime.now()
                        if key == "seconds":
                            factor = current_time.second / 59
                        elif key == "minutes":
                            factor = current_time.minute / 59
                        elif key == "hours":
                            factor = current_time.hour / 23
                        else:
                            metric = key
                            if metric not in self.metrics.get_metrics(self.temp_unit):
                                print(f"Warning: {metric} not found in metrics, using start color.")
                                factor = 0
                            if self.metrics_min_value[metric] == self.metrics_max_value[metric]:
                                print(f"Warning: {metric} min and max values are the same, using start color.")
                                factor = 0
                            else:
                                factor = (self.metrics.get_metrics(self.temp_unit)[metric]-self.metrics_min_value[metric]) / (self.metrics_max_value[metric]-self.metrics_min_value[metric])
                                if factor > 1:
                                    factor = 1
                                    print(f"Warning: {metric} value exceeds max value, clamping to 1.")
                                elif factor < 0:
                                    factor = 0
                                    print(f"Warning: {metric} value below min value, clamping to 0.")
                    else:
                        start_color, end_color = split_color

                        factor = 1 - abs((self.cpt%self.cycle_duration) - (self.cycle_duration/2)) / (self.cycle_duration/2)
                    
                    colors.append(interpolate_color(start_color, end_color, factor))
                else:
                    colors.append(color)
        return np.array(colors)
    
    def update(self):
        self.leds = np.array([0] * NUMBER_OF_LEDS)
        self.config = self.load_config()
        if self.config:
            VENDOR_ID = int(self.config.get('vendor_id', "0x0416"),16)
            PRODUCT_ID = int(self.config.get('product_id', "0x8001"),16)
            self.metrics_max_value = {
                "cpu_temp": self.config.get('cpu_max_temp', 90),
                "gpu_temp": self.config.get('gpu_max_temp', 90),
                "cpu_usage": self.config.get('cpu_max_usage', 100),
                "gpu_usage": self.config.get('gpu_max_usage', 100),
            }
            self.metrics_min_value = {
                "cpu_temp": self.config.get('cpu_min_temp', 30),
                "gpu_temp": self.config.get('gpu_min_temp', 30),
                "cpu_usage": self.config.get('cpu_min_usage', 0),
                "gpu_usage": self.config.get('gpu_min_usage', 0),
            }
            self.display_mode = self.config.get('display_mode', 'metrics')
            self.metrics_colors = self.get_config_colors(self.config, key="metrics")
            self.time_colors = self.get_config_colors(self.config, key="time")
            self.update_interval = self.config.get('update_interval', 0.1)
            self.cycle_duration = int(self.config.get('cycle_duration', 5)/self.update_interval)
            self.metrics.update_interval = self.config.get('metrics_update_interval', 0.5)
            if self.config.get('layout_mode', 'big')== 'small':
                self.leds_indexes = leds_indexes_small
                if self.display_mode not in display_modes_small:
                    print(f"Warning: Display mode {self.display_mode} not compatible with small layout, switching to alternate metrics.")
                    self.display_mode = "alternate_metrics"
            else:
                self.leds_indexes = leds_indexes
                if self.display_mode not in display_modes:
                    print(f"Warning: Display mode {self.display_mode} not compatible with big layout, switching to metrics.")
                    self.display_mode = "metrics"
        else:
            VENDOR_ID = 0x0416
            PRODUCT_ID = 0x8001
            self.metrics_max_value = {
                "cpu_temp": 90,
                "gpu_temp": 90,
                "cpu_usage": 100,
                "gpu_usage": 100,
            }
            self.metrics_min_value = {
                "cpu_temp": 30,
                "gpu_temp": 30,
                "cpu_usage": 0,
                "gpu_usage": 0,
            }
            self.display_mode = 'metrics'
            self.time_colors = np.array(["ffe000"] * NUMBER_OF_LEDS)
            self.metrics_colors = np.array(["ff0000"] * NUMBER_OF_LEDS)
            self.update_interval = 0.1
            self.cycle_duration = int(5/self.update_interval)
            self.metrics.update_interval = 0.5
            self.leds_indexes = leds_indexes
        

        if VENDOR_ID != self.VENDOR_ID or PRODUCT_ID != self.PRODUCT_ID:
            print(f"Warning: Config VENDOR_ID or PRODUCT_ID changed, reinitializing device.")
            self.VENDOR_ID = VENDOR_ID
            self.PRODUCT_ID = PRODUCT_ID
            self.dev = self.get_device()

    def display(self):
        while True:
            self.config = self.load_config()
            self.update()
            if self.dev is None:
                print("No device found, with VENDOR_ID: {}, PRODUCT_ID: {}".format(self.VENDOR_ID, self.PRODUCT_ID))
                time.sleep(5)
            else:
                if self.display_mode == "alternate_time":
                    if self.cpt < self.cycle_duration:
                        self.display_time()
                        self.display_metrics(devices=['gpu'])
                    else:
                        self.display_time(device="gpu")
                        self.display_metrics(devices=['cpu'])
                elif self.display_mode == "metrics":
                    self.display_metrics(devices=["cpu", "gpu"])
                elif self.display_mode == "time":
                    self.display_time_with_seconds()
                elif self.display_mode == "time_cpu":
                    self.display_time(device="gpu")
                    self.display_metrics(devices=['cpu'])
                elif self.display_mode == "time_gpu":
                    self.display_time()
                    self.display_metrics(devices=['gpu'])
                elif self.display_mode == "alternate_time_with_seconds":
                    if self.cpt < self.cycle_duration:
                        self.display_time_with_seconds()
                    else:
                        self.display_metrics()
                elif self.display_mode == "alternate_metrics":
                    if self.cpt < self.cycle_duration/2:
                        self.display_temp_small(device='cpu')
                    elif self.cpt < self.cycle_duration:
                        self.display_temp_small(device='gpu')
                    elif self.cpt < 3*self.cycle_duration/2:
                        self.display_usage_small(device='cpu')
                    else:
                        self.display_usage_small(device='gpu')
                elif self.display_mode == "cpu_temp":
                    self.display_temp_small(device='cpu')
                elif self.display_mode == "gpu_temp":
                    self.display_temp_small(device='gpu')
                elif self.display_mode == "cpu_usage":
                    self.display_usage_small(device='cpu')
                elif self.display_mode == "gpu_usage":
                    self.display_usage_small(device='gpu')
                elif self.display_mode == "debug_ui":
                    self.colors = self.metrics_colors
                    self.leds[:] = 1
                else:
                    print(f"Unknown display mode: {self.display_mode}")
                
                self.cpt = (self.cpt + 1) % (self.cycle_duration*2)
                self.send_packets()
            time.sleep(self.update_interval)



def main(config_path, test_mode=False):
    controller = Controller(config_path=config_path)

    if test_mode:
        print("=== DIGIT TEST MODE ===")
        print("Cycling through digits 0-9 every 2 seconds on all matrices")
        print("Press Ctrl+C to stop\n")
        try:
            while True:
                controller.update()
                controller.display_digit_test()
                controller.send_packets()
                time.sleep(0.1)  # Update display faster for smoother cycling
        except KeyboardInterrupt:
            print("\nTest mode stopped")
            controller.clear()
            controller.show()
    else:
        controller.display()

if __name__ == '__main__':
    test_mode = '--test' in sys.argv

    # Remove --test from arguments if present
    args = [arg for arg in sys.argv[1:] if arg != '--test']

    if len(args) > 0:
        config_path = args[0]
        print(f"Using config path: {config_path}")
    else:
        print("No config path provided, using default.")
        config_path = None

    main(config_path, test_mode=test_mode)

