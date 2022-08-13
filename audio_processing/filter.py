import pyaudio
import wave

BUFFER_SIZE = 2 ** 6

class Channel():
    def __init__(self):
        self.filters = []
        self.buffer = []

class Buffer():
    """A simple object that contains a buffer.
    Instead of this, you could just use a list as the buffer,
    but this class gives me the option to implement more features such as
    an offset point or something in the future."""
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
        self.lowpass_filter = Convolution(moving_average_ir(20))

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

def process(channel, sample_width):
    channel.buffer = wav_to_num_samp(channel.buffer, sample_width)
    channel.buffer = Buffer(channel.buffer)
    for filter in channel.filters:
        channel.buffer = filter.execute(channel.buffer)
    channel.buffer = num_samp_to_wav(channel.buffer.buffer, sample_width)
    return channel

def main():
    # open the wave files
    file_1 = wave.open("audio/whistle.wav", "rb")
    file_2 = wave.open("audio/voice.wav", "rb")
    sample_width = file_1.getsampwidth()
    # initialize pyaudio
    p = init_pyaudio()
    print(pyaudio.get_format_from_width(sample_width))
    # initialize the stream
    stream = p.open(format =p.get_format_from_width(sample_width),
                    channels = 1,
                    rate = int(file_1.getframerate()),
                    output = True)

    #create the filters
    lowpass1 = Convolution(moving_average_ir(2))
    lowpass2 = Convolution(moving_average_ir(20))
    slow = PlaybackSpeed(.75)

    #main loop
    while True:
        in_1 = get_buffer_from_file(file_1, sample_width) #get buffers from files
        in_2 = get_buffer_from_file(file_2, sample_width)
        output = mix(in_1, in_2) #mix them together
        if len(output.buffer) == 0: #check for stop condition
            break
        ######## MIX BUS PROCESSING STARTS HERE ########
        output = slow.execute(output)
        output = lowpass2.execute(output)
        ################################################
        play(output, sample_width, stream) #play the audio

    # stop and close the stream and pyaudio
    stream.stop_stream()
    stream.close()
    p.terminate()
    return

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

def get_buffer_from_file(file, sample_width):
    return Buffer(wav_to_num_samp(file.readframes(BUFFER_SIZE), sample_width))

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

def play(output, sample_width, stream):
    threshold = (2 ** (sample_width * 8 - 1)) - 1
    for i, val in enumerate(output.buffer):
        if not -threshold < val < threshold:
            print("~~~Clipped~~~")
            if val > threshold:
                output.buffer[i] = threshold
            else:
                output.buffer[i] = -threshold
    stream.write(num_samp_to_wav(output.buffer, sample_width))
    return

def init_pyaudio(): #initializes pyaudio
    p = pyaudio.PyAudio()
    return p

if __name__ == "__main__":
    main()
