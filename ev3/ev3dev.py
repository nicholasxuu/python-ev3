import os
import glob
import sys
import warnings
import logging
import re
import subprocess

logger = logging.getLogger(__name__)


class NoSuchSensorError(Exception):

	def __init__(self, port, name=None):
		self.port = port
		self.name = name

	def __str__(self):
		return "No such sensor port=%d name=%s" % (self.port, self.name)


class NoSuchMotorError(Exception):

	def __init__(self, port, _type):
		self.port = port
		self._type = _type

	def __str__(self):
		return "No such motor port=%s type=%s" % (self.port, self._type)


class NoSuchLibraryError(Exception):

	def __init__(self, lib=""):
		self.lib = lib

	def __str__(self):
		return "No such library %s" % self.lib


class Ev3StringType(object):

	@staticmethod
	def post_read(value):
		return value

	@staticmethod
	def pre_write(value):
		return value


class Ev3IntType(object):

	@staticmethod
	def post_read(value):
		return int(value)

	@staticmethod
	def pre_write(value):
		return str(value)


class Ev3BoolType(object):

	@staticmethod
	def post_read(value):
		return bool(value)

	@staticmethod
	def pre_write(value):
		return '1' if value else '0'


class Ev3OnOffType(object):

	@staticmethod
	def post_read(value):
		return True if value == 'on' else False

	@staticmethod
	def pre_write(value):
		if (value == 'on' or value == 'off'):
			return value
		else:
			return 'on' if bool(value) else 'off'


class create_ev3_property(object):

	def __init__(self, **kwargs):
		self.kwargs = kwargs

	def __call__(self, cls):
		for name, args in self.kwargs.items():
			def ev3_property(name, read_only=False, property_type=Ev3StringType):
				def fget(self):
					return property_type.post_read(self.read_value(name))

				def fset(self, value):
					self.write_value(
						name, property_type.pre_write(value))
				return property(fget, None if read_only else fset)

			setattr(cls, name, ev3_property(name, **args))

		return cls


def get_battery_percentage():
	"""
	Return an int() of the percentage of battery life remaining
	"""
	voltage_max = None
	voltage_min = None
	voltage_now = None

	with open('/sys/devices/platform/legoev3-battery/power_supply/legoev3-battery/uevent', 'r') as fh:
		for line in fh:

			if not voltage_max:
				re_voltage_max = re.search(
					'POWER_SUPPLY_VOLTAGE_MAX_DESIGN=(\d+)', line)

				if re_voltage_max:
					voltage_max = int(re_voltage_max.group(1))
					continue

			if not voltage_min:
				re_voltage_min = re.search(
					'POWER_SUPPLY_VOLTAGE_MIN_DESIGN=(\d+)', line)

				if re_voltage_min:
					voltage_min = int(re_voltage_min.group(1))
					continue

			if not voltage_now:
				re_voltage_now = re.search(
					'POWER_SUPPLY_VOLTAGE_NOW=(\d+)', line)

				if re_voltage_now:
					voltage_now = int(re_voltage_now.group(1))

			if re_voltage_max and re_voltage_min and re_voltage_now:
				break

	if voltage_max and voltage_min and voltage_now:

		# This happens with the EV3 rechargeable battery if it is fully charge
		if voltage_now >= voltage_max:
			return 100

		# Haven't seen this scenario but it can't hurt to check for it
		elif voltage_now <= voltage_min:
			return 0

		# voltage_now is between the min and max
		else:
			voltage_max -= voltage_min
			voltage_now -= voltage_min
			return int(voltage_now / float(voltage_max) * 100)
	else:
		logger.error('voltage_max %s, voltage_min %s, voltage_now %s' %
					 (voltage_max, voltage_min, voltage_now))
		return 0


class Ev3Dev(object):

	def __init__(self):
		self.sys_path = ""

	def read_value(self, name):
		attr_file = os.path.join(self.sys_path, name)
		if os.path.isfile(attr_file):
			with open(attr_file) as f:
				value = f.read().strip()
				return value
		else:
			return None

	def write_value(self, name, value):
		attr_file = os.path.join(self.sys_path, name)
		if os.path.isfile(attr_file):
			with open(attr_file, 'w') as f:
				f.write(str(value))
		else:
			return


@create_ev3_property(
	bin_data={'read_only': True},
	bin_data_format={'read_only': True},
	decimals={'read_only': True},
	#mode={ 'read_only': False},
	modes={'read_only': True},
	name={'read_only': True},
	port_name={'read_only': True},
	uevent={'read_only': True},
	units={'read_only': True},
	value0={'read_only': True, 'property_type': Ev3IntType},
	value1={'read_only': True, 'property_type': Ev3IntType},
	value2={'read_only': True, 'property_type': Ev3IntType},
	value3={'read_only': True, 'property_type': Ev3IntType},
	value4={'read_only': True, 'property_type': Ev3IntType},
	value5={'read_only': True, 'property_type': Ev3IntType},
	value6={'read_only': True, 'property_type': Ev3IntType},
	value7={'read_only': True, 'property_type': Ev3IntType}
)
class LegoSensor(Ev3Dev):

	def __init__(self, port=-1, name=None):
		Ev3Dev.__init__(self)
		sensor_existing = False
		if (port > 0):
			self.port = port
			for p in glob.glob('/sys/class/lego-sensor/sensor*/port_name'):
				with open(p) as f:
					value = f.read().strip()
					if (value == 'in' + str(port)):
						self.sys_path = os.path.dirname(p)
						sensor_existing = True
						break
		if (len(glob.glob('/sys/class/lego-sensor/sensor*/driver_name')) > 0 and name != None and port == -1):
			for p in glob.glob('/sys/class/lego-sensor/sensor*/driver_name'):
				with open(p) as f:
					value = f.read().strip()
					if (name in value):
						self.sys_path = os.path.dirname(p)
						self.port = int(self.port_name[2:])
						sensor_existing = True
						break
		if (not sensor_existing):
			raise NoSuchSensorError(port, name)
		self._mode = self.read_value('mode')

	@property
	def mode(self):
		return self._mode

	@mode.setter
	def mode(self, value):
		if (self._mode != value):
			self._mode = value
			self.write_value('mode', value)

	def mode_force_flush(self, value):
		self._mode = value
		self.write_value('mode', value)


class Enum(object):

	def __init__(self, *args, **kwargs):
		for arg in args:
			kwargs[arg] = arg
		self.enum_dict = kwargs

	def __getattr__(self, name):
		if (name in self.enum_dict.keys()):
			return self.enum_dict[name]
		else:
			raise NameError("no such item %s" % name)


@create_ev3_property(
	command={'read_only': False, 'property_type': Ev3StringType},
	commands={'read_only': True, 'property_type': Ev3StringType},
	count_per_rot={'read_only': True, 'property_type': Ev3IntType},
	driver_name={'read_only': True, 'property_type': Ev3StringType},
	duty_cycle={'read_only': True, 'property_type': Ev3IntType},
	duty_cycle_sp={'read_only': False, 'property_type': Ev3IntType},
	encoder_polarity={'read_only': False, 'property_type': Ev3StringType},
	polarity={'read_only': False, 'property_type': Ev3StringType},
	port_name={'read_only': True, 'property_type': Ev3StringType},
	position={'read_only': False, 'property_type': Ev3IntType},
	position_sp={'read_only': False, 'property_type': Ev3IntType},
	#ramp_down_sp={'read_only': False, 'property_type': Ev3IntType},
	#ramp_up_sp={'read_only': False, 'property_type': Ev3IntType},
	speed={'read_only': True, 'property_type': Ev3IntType},
	speed_regulation={'read_only': False, 'property_type': Ev3StringType},
	speed_sp={'read_only': False, 'property_type': Ev3IntType},
	state={'read_only': True, 'property_type': Ev3StringType},
	stop_command={'read_only': False, 'property_type': Ev3StringType},
	stop_commands={'read_only': True, 'property_type': Ev3StringType},
	time_sp={'read_only': False, 'property_type': Ev3IntType},
	uevent={'read_only': True, 'property_type': Ev3StringType},
)
class Motor(Ev3Dev):
	STOP_MODE = Enum(COAST='coast', BRAKE='brake', HOLD='hold')
	POSITION_MODE = Enum(RELATIVE='relative', ABSOLUTE='absolute')
	PORT = Enum('A', 'B', 'C', 'D')

	def __init__(self, port='', _type=''):
		Ev3Dev.__init__(self)
		motor_existing = False
		self.regulation_mode = False
		searchpath = '/sys/class/tacho-motor/motor*/'
		if (len(glob.glob(searchpath + "*")) == 0):
			searchpath = '/sys/class/tacho-motor/tacho-motor*/'
		if (port != ''):
			self.port = port
			for p in glob.glob(searchpath + 'port_name'):
				with open(p) as f:
					value = f.read().strip()
					if (value.lower() == ('out' + port).lower()):
						self.sys_path = os.path.dirname(p)
						motor_existing = True
						break
		if (_type != '' and port == ''):
			for p in glob.glob(searchpath + 'type'):
				with open(p) as f:
					value = f.read().strip()
					if (value.lower() == _type.lower()):
						self.sys_path = os.path.dirname(p)
						self.port = self.port_name[3:]
						motor_existing = True
						break
		if (not motor_existing):
			raise NoSuchMotorError(port, _type)

	def set_regulation_mode(self, regulation_mode):
		"""
		:param regulation_mode: True = constant speed, False(default) = un-regulated speed by battery voltage.
		:type regulation_mode: bool
		"""
		self.regulation_mode = regulation_mode

	def stop(self):
		self.run = False
		self.command = 'stop'

	def reset(self):
		self.run = False
		self.command = 'reset'

	def get_position(self):
		"""
		:return: current motor position
		:rtype: int
		"""
		return self.position

	def set_attrs(self, kwargs):
		"""
		:param kwargs: general function to help other functions setting extra parameters
		"""
		for k in kwargs:
			v = kwargs[k]
			if (v != None):
				setattr(self, k, v)

	def set_stop_command(self, stop_command):
		"""
		:param stop_command: coast(default), brake, hold(for run limited position)
		:type stop_command: str
		"""
		self.stop_command = stop_command

	def run_forever(self, speed_sp, **kwargs):
		"""
		:param speed_sp: rotation speed, -100 to 100, positive or negative to decide direction
		:type speed_sp: int
		:param kwargs: all other values
		"""
		self.reset()

		self.run_mode = 'forever'
		self.set_attrs(kwargs)
		self.speed_sp = speed_sp
		if self.regulation_mode:
			self.speed_regulation = 'on'
		else:
			self.speed_regulation = 'off'
		self.run = True
		self.command = 'run-forever'

	def run_direct(self, speed_sp, **kwargs):
		"""
		Continue running at new speed
		"""
		if self.run_mode != 'forever':
			self.run_mode = 'forever'
		self.set_attrs(kwargs)
		self.speed_sp = speed_sp
		if self.regulation_mode:
			self.speed_regulation = 'on'
		else:
			self.speed_regulation = 'off'
		self.run = True
		self.command = 'run-forever'
		pass

	def run_to_abs_pos(self, position_sp):
		"""
		:param position_sp: motor position to run towards,
		:type position_sp: int
		"""
		if position_sp is not None:
			self.position_sp = position_sp
		self.run = True
		stop_command = self.stop_command
		self.stop_command = 'hold' # made for run to position
		self.command = 'run-to-abs-pos'
		self.stop_command = stop_command

	def run_to_rel_pos(self, position_sp=None):
		"""
		:param position_sp: run degree of position every time the function is called
		:type position_sp: int
		"""
		if position_sp is not None:
			self.position_sp = position_sp
		self.run = True
		stop_command = self.stop_command
		self.stop_command = 'hold' # made for run to position
		self.command = 'run-to-rel-pos'
		self.stop_command = stop_command

	def run_time_limited(self, time_sp, speed_sp, **kwargs):
		"""
		:param time_sp: time (ms) to run
		:type time_sp: int
		:param speed_sp: speed to run at (degree per second)
		:type speed_sp: int
		"""
		self.run_mode = 'time'
		self.set_attrs(kwargs)
		self.speed_sp = speed_sp
		if self.regulation_mode:
			self.speed_regulation = 'on'
		else:
			self.speed_regulation = 'off'
		self.time_sp = time_sp
		self.run = True
		self.command = 'run-timed'

	def run_position_limited(self, position_sp, speed_sp, **kwargs):
		"""
		:param position_sp: degree of position to run in this round.
		:type position_sp: int
		:param speed_sp: speed to run at
		:type speed_sp: int
		"""
		self.run_mode = 'position'
		self.set_attrs(kwargs)
		# duty_cycle_sp doesn't work well with position, force set to speed_regulation + speed_sp
		self.speed_regulation = 'on'
		self.speed_sp = speed_sp
		self.run_to_rel_pos(position_sp)

	def run_to_position(self, position_sp, speed_sp, **kwargs):
		"""
		:param position_sp: degree to position to run towards.
		:type position_sp: int
		:param speed_sp: speed to run at
		:type speed_sp: int
		"""
		self.run_mode = 'position'
		self.set_attrs(kwargs)
		# duty_cycle_sp doesn't work well with position, force set to speed_regulation + speed_sp
		self.speed_regulation = 'on'
		self.speed_sp = speed_sp
		self.run_to_abs_pos(position_sp)


def I2CSMBusProxy(cls):
	try:
		from smbus import SMBus
		smbus_proxied_methods = [
			m for m in dir(SMBus) if (m.startswith('read') or m.startswith('write'))]
		for m in smbus_proxied_methods:
			def create_proxied_smb_method(method):
				def proxied_smb_method(self, *args, **kwargs):
					return getattr(self.b, method)(self.addr, *args, **kwargs)
				return proxied_smb_method
			setattr(cls, m,  create_proxied_smb_method(m))
		return cls
	except ImportError:
		warnings.warn('python-smbus binding not found!')
		return cls


@I2CSMBusProxy
class I2CS(object):

	def __init__(self, port, addr):
		self.port = port
		self.i2c_port = port + 2
		self.sys_path = '/dev/i2c-%s' % self.i2c_port
		if (not os.path.exists(self.sys_path)):
			raise NoSuchSensorError(port)
		try:
			from smbus import SMBus
			self.b = SMBus(self.i2c_port)
			self.addr = addr
		except ImportError:
			raise NoSuchLibraryError('smbus')

	def read_byte_array(self, reg, _len):
		return [self.read_byte_data(reg + r) for r in range(_len)]

	def read_byte_array_as_string(self, reg, _len):
		return ''.join(chr(r) for r in self.read_byte_array(reg, _len))

	class create_i2c_property(object):

		def __init__(self, **kwargs):
			self.kwargs = kwargs

		def __call__(self, cls):
			for name, reg_address_and_read_only in self.kwargs.items():
				def i2c_property(reg, read_only=True):
					def fget(self):
						return self.read_byte_data(reg)

					def fset(self, value):
						return self.write_byte_data(reg, value)
					return property(fget, None if read_only else fset)
				if (type(reg_address_and_read_only) == int):
					prop = i2c_property(reg_address_and_read_only)
				else:
					prop = i2c_property(
						reg_address_and_read_only[0], **reg_address_and_read_only[1])
				setattr(cls, name, prop)
			return cls


@create_ev3_property(
	brightness={'read_only': False, 'property_type': Ev3IntType},
	max_brightness={'read_only': True, 'property_type': Ev3IntType},
	trigger={'read_only': False},
	delay_on={'read_only': False, 'property_type': Ev3IntType},
	delay_off={'read_only': False, 'property_type': Ev3IntType}
)
class LEDLight(Ev3Dev):

	def __init__(self, light_path):
		super(Ev3Dev, self).__init__()
		self.sys_path = '/sys/class/leds/' + light_path


class LEDSide (object):

	def __init__(self, left_or_right):
		self.green = LEDLight('ev3:green:%s' % left_or_right)
		self.red = LEDLight('ev3:red:%s' % left_or_right)
		self._color = (0, 0)

	@property
	def color(self):
		"""LED color (RED, GREEN), where RED and GREEN are integers
		between 0 and 255."""
		return self._color

	@color.setter
	def color(self, value):
		assert len(value) == 2
		assert 0 <= value[0] <= self.red.max_brightness
		assert 0 <= value[1] <= self.green.max_brightness
		self._color = (
			self.red.brightness, self.green.brightness) = tuple(value)

	def blink(self, color=(0, 0), **kwargs):
		if (color != (0, 0)):
			self.color = color
		for index, light in enumerate((self.red, self.green)):
			if (not self._color[index]):
				continue
			light.trigger = 'timer'
			for p, v in kwargs.items():
				setattr(light, p, v)

	def on(self):
		self.green.trigger, self.red.trigger = 'none', 'none'
		self.red.brightness, self.green.brightness = self._color

	def off(self):
		self.green.trigger, self.red.trigger = 'none', 'none'
		self.red.brightness, self.green.brightness = 0, 0


class LED(object):

	class COLOR:
		NONE = (0, 0)
		RED = (255, 0)
		GREEN = (0, 255)
		YELLOW = (25, 255)
		ORANGE = (120, 255)
		AMBER = (255, 255)

	left = LEDSide('left')
	right = LEDSide('right')


@create_ev3_property(
	tone={'read_only': False},
	mode={'read_only': True},
	volume={'read_only': False, 'property_type': Ev3IntType}
)
class Tone(Ev3Dev):

	def __init__(self):
		super(Ev3Dev, self).__init__()
		self.sys_path = '/sys/devices/platform/snd-legoev3'

	def play(self, frequency, milliseconds=1000):
		self.tone = '%d %d' % (frequency, milliseconds)

	def stop(self):
		self.tone = '0'


class Lcd(object):

	def __init__(self):
		try:
			from PIL import Image, ImageDraw

			SCREEN_WIDTH = 178
			SCREEN_HEIGHT = 128
			HW_MEM_WIDTH = int((SCREEN_WIDTH + 31) / 32) * 4
			SCREEN_MEM_WIDTH = int((SCREEN_WIDTH + 7) / 8)
			LCD_BUFFER_LENGTH = SCREEN_MEM_WIDTH * SCREEN_HEIGHT
			LCD_HW_BUFFER_LENGTH = HW_MEM_WIDTH * SCREEN_HEIGHT
			self._buffer = Image.new(
				"1", (HW_MEM_WIDTH * 8, SCREEN_HEIGHT), "white")
			self._draw = ImageDraw.Draw(self._buffer)
		except ImportError:
			raise NoSuchLibraryError('PIL')

	def update(self):
		f = os.open('/dev/fb0', os.O_RDWR)
		os.write(f, self._buffer.tobytes("raw", "1;IR"))
		os.close(f)

	@property
	def buffer(self):
		return self._buffer

	@property
	def draw(self):
		return self._draw

	def reset(self):
		self._draw.rectangle(
			(0, 0) + self._buffer.size, outline='white', fill='white')


class attach_ev3_keys(object):

	def __init__(self, **kwargs):
		self.kwargs = kwargs

	def __call__(self, cls):
		key_const = {}
		for key_name, key_code in self.kwargs.items():
			def attach_key(key_name, key_code):
				def fget(self):
					buf = self.polling()
					return self.test_bit(key_code, buf)
				return property(fget)

			setattr(cls, key_name, attach_key(key_name, key_code))
			key_const[key_name.upper()] = key_code
		setattr(cls, 'CODE', Enum(**key_const))
		return cls


import array
import fcntl


@attach_ev3_keys(
	up=103,
	down=108,
	left=105,
	right=106,
	enter=28,
	backspace=14
)
class Key(object):

	def __init__(self):
		pass

	def EVIOCGKEY(self, length):
		return 2 << (14 + 8 + 8) | length << (8 + 8) | ord('E') << 8 | 0x18

	def test_bit(self, bit, bytes):
		# bit in bytes is 1 when released and 0 when pressed
		return not bool(bytes[int(bit / 8)] & 1 << bit % 8)

	def polling(self):
		KEY_MAX = 0x2ff
		BUF_LEN = int((KEY_MAX + 7) / 8)
		buf = array.array('B', [0] * BUF_LEN)
		with open('/dev/input/by-path/platform-gpio-keys.0-event', 'r') as fd:
			ret = fcntl.ioctl(fd, self.EVIOCGKEY(len(buf)), buf)
		if (ret < 0):
			return None
		else:
			return buf
