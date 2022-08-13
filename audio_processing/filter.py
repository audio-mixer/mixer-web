import wave

class Channel():
    def __init__(self):
        self.filters = {}
        self.buffer = []

class Buffer():
    """A simple object that contains a buffer.
    Instead of this, you could just use a list as the buffer,
    but this class gives me the option to implement more features such as
    an offset point or something in the future.
    Update: it's been several days and I think this class is just an unnecessary
    pain in the ass"""
    def __init__(self, buffer = []):
        self.buffer = buffer

class Rollover():
    """Parent class for filters that need rollover. Privides self.rollover to store
    the rollover between clock cycles, and the handle_rollover method to split the
    output from the rollover, store the rollover, and return the output"""
    def __init__(self):
        self.rollover = []

    def handle_rollover(self, output, length):
        """Takes the output and output length, adds the previous clock cycle's
        rollover into the output, stores the new rollover, and returns
        the correctly sized output buffer."""
        #add the rollover from the last clock cycle into the buffer
        mix(output, self.rollover)
        #store this cycle's rollover
        self.rollover = output[length:]
        #return the correctly sized output as a buffer object
        return Buffer(output[:length])

class Convolution(Rollover):
    def __init__(self, kernel = [1]):
        super().__init__()
        self.kernel = kernel

    def execute(self, input):
        #call the convolve function (seperated from this method because it is useful elsewhere)
        output = convolve(input.buffer, self.kernel)
        #call the rollover method to handle the rollover and return the correctly sized output buffer object.
        return self.handle_rollover(output, len(input.buffer))

class PlaybackSpeed():
    def __init__(self, speed):
        self.speed = speed
        self.lowpass_filter = Convolution(moving_average_ir(10))

    def execute(self, input):
        step = 1 / self.speed #how many output samples per input sample (on average)
        output = []
        #copy each sample in the input into the output several times
        for i, sample in enumerate(input.buffer):
            while i * step >= len(output):
                output.append(sample)
        #convert output to a buffer object so we can pass it to toe convolution filter
        output = Buffer(output)
        #filter the output to remove aliasing
        output = self.lowpass_filter.execute(output)
        #this object doesn't have a rollover, though its filter does.
        return output

def process(channels, raw_wav, sample_width):
    wav_channels = separate_wav_channels(raw_wav, len(channels), sample_width)
    #wav_channels[0] is an empty bytes object for some reasaon..
    num_channels = [wav_to_num_samp(wav_channel, sample_width) for wav_channel in wav_channels]

    for channel, num_channel in zip(channels, num_channels):
        channel.buffer = Buffer(num_channel)
        for filter in channel.filters.values():
            channel.buffer = filter.execute(channel.buffer)
        channel.buffer.buffer = num_samp_to_wav(channel.buffer.buffer, sample_width)
    return channels

def mix(in_1, in_2, *args, length = False):
    #if buffer objects were given, extract the lists.
    buffer = False
    if isinstance(in_1, Buffer):
        in_1 = in_1.buffer
        buffer = True
    if isinstance(in_2, Buffer):
        in_2 = in_2.buffer
    #for each input in *args, mix the input into in_1
    for input in args:
        in_1 = mix(in_1, input)
    #if input 1 is shorter, re-run the function with inputs flipped. in_1 needs to be the longer list.
    if len(in_1) < len(in_2):
        return mix(in_2, in_1)
    else:
        #if no length was passed, set the length to the longest list (in_1),
        #otherwise, the length argument will be used to determine loop length
        if not length:
            length = len(in_1)
        for i in range(length):
            try:
                in_1[i] += in_2[i]
            except:
                break
    #if in_1 was a buffer object, return the output as a buffer object.
    if buffer:
        return Buffer(in_1[:length])
    return in_1[:length]

def convolve(input, kernel):
    #create the output buffer with enough samples to hold the output's rollover
    output = [0 for i in range(len(input) + len(kernel) - 1)]
    #for each input sample, write the kernel into the output buffer, scaled by the value of the sample
    for in_index, in_val in enumerate(input):
        for kernel_index, kernel_val in enumerate(kernel):
            output[in_index + kernel_index] += kernel_val * in_val
    #round AFTER all the calculations
    for i, val in enumerate(output):
        output[i] = int(val)
    return output

def moving_average_ir(strength):
    return [1/strength for i in range(strength)]

def create_channels(wave):
    channels = []
    for i in range(wave.getnchannels()):
        channel = Channel()
        channel.filters["lowpass"] = Convolution(moving_average_ir(15))
        channel.filters["speed"] = PlaybackSpeed(1.2)
        channels.append(channel)
    return channels

def get_buffer_from_file(file, sample_width):
    return Buffer(wav_to_num_samp(file.readframes(BUFFER_SIZE), sample_width))

def separate_wav_channels(raw_wav, n_channels, sample_width):
    wav_channels = []
    for i in range(n_channels):
        wav_channels.append(bytes())
        for j in range(len(raw_wav[::sample_width])):
            wav_channels[i] += raw_wav[(i * sample_width) + (j * sample_width) :
                                       (i * sample_width) + ((j + 1) * sample_width)]
    return wav_channels

def combine_wav_channels(channels, sample_width):
    output = bytes()
    for i in range(len(channels[0].buffer.buffer[::sample_width])):
        for channel in channels:
            output += channel.buffer.buffer[i * sample_width : (i + 1) * sample_width]
    return output

def wav_to_num_samp(buffer, sample_width):
    num_buffer = []
    for i in range(len(buffer[::sample_width])):
        num_buffer.append(int.from_bytes(buffer[i * sample_width : (i + 1) * sample_width],
                                         byteorder = "little",
                                         signed = True))
    return num_buffer

def num_samp_to_wav(buffer, sample_width):
    output_buffer = bytes()
    for sample in buffer:
        output_buffer += sample.to_bytes(sample_width,"little",signed = True)
    return output_buffer
