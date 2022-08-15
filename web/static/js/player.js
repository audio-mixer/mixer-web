const protocol = location.protocol == "http:" ? "ws" : "wss";
const ws = new WebSocket(`${protocol}://${location.host}/stream`);
ws.binaryType = "arraybuffer";

const BUFFER_SIZE = 10;

let context;
let source;
let interval;
let time = 0;
let init = 0;
let nextTime = 0;
let active_buffer = 0;
let audioStack = [];
let streaming = false;
let duration = { hours: 0, minuets: 0, seconds: 0 };

try {
    window.AudioContext = window.AudioContext || window.webkitAudioContext;
} catch (e) {
    alert("Web Audio API is not supported in this browser");
}

// handle audio player btn interations
const timer = document.querySelector(".timer");
const player = document.querySelector(".player");
const stopbtn = document.querySelector(".stopbtn");
const progress = document.querySelector(".progress");
const playbackToggle = document.querySelector(".playback-tg");
stopbtn.addEventListener("click", (e) => {if (!e.target.classList.contains("gray")) stop()});
playbackToggle.addEventListener("click", (e) => {
    element = e.target;
    if (element.classList.contains("gray")) {
        return;
    }

    // start playback
    if (context == undefined || context.state == "closed") {
        stream("example.wav");
        return;
    }

    // pause playback
    if (context.state == "running") {
        playbackToggle.classList.add("bi-play-fill");
        playbackToggle.classList.remove("bi-pause-fill");
        context.suspend();
        streaming = false;
        return;
    }

    // resume playback
    if (context.state == "suspended") {
        context.resume();
        streaming = true;
        playbackToggle.classList.add("bi-pause-fill");
        playbackToggle.classList.remove("bi-play-fill");
        return;
    }
});

// handle the incomming audio data
ws.onmessage = (message) => {
    if (message.data instanceof ArrayBuffer) {
        context.decodeAudioData(message.data, (buffer) => {
            audioStack.push(buffer);
            if ((init != 0) || (audioStack.length > 2)) {
                init++;
                playBuffer();
            }
        });

        return;
    }

    data = JSON.parse(message.data);
    cmdUsed = data.command;
    switch (cmdUsed) {
        case "GET":
            duration = data.duration;
            break;
    }
};

// begin recieving audio chunks over websockets
function stream(source = "example.wav") {
    // reset varuables
    [init, nextTime] = [0, 0];

    // create audio context
    context = new AudioContext();

    // initially send information to the server to fetch the audio stream
    streaming = true;
    ws.send(JSON.stringify({
        source: source,
        commands: ["STREAM", "GET"],
    }));

    stopbtn.classList.remove("gray");
    playbackToggle.classList.add("bi-pause-fill");
    playbackToggle.classList.remove("bi-play-fill");
}

// begin playing audio from buffer
function playBuffer() {
    while (audioStack.length) {
        let buffer = audioStack.shift();
        source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(context.destination);
        if (nextTime == 0) {
            nextTime = context.currentTime + 0.05;
        }

        source.start(nextTime);
        nextTime += source.buffer.duration;
        source.addEventListener("ended", () => {
            active_buffer--;
        });
    }
}

// stops playback
function stop() {
    if (context == undefined || context.state == "closed") {
        return;
    }

    context.close();
    [init, nextTime] = [0, 0];
    ws.send(JSON.stringify({
        commands: ["STOP"],
    }));

    time = 0;
    active_buffer = 0;
    streaming = false;
    progress.style.width = "0%"
    timer.innerText = `0:00 / 0:00`;
    stopbtn.classList.add("gray");
    playbackToggle.classList.remove("gray");
    playbackToggle.classList.add("bi-play-fill");
    playbackToggle.classList.remove("bi-pause-fill");
}

// custom listeners
setInterval(() => {

    if (streaming) {
        if (active_buffer <= BUFFER_SIZE) {

            active_buffer++;
            ws.send(JSON.stringify({
                commands: ["NEXT"]
            }));
        }
    }
})

function startInterval(ms) {
    interval = setInterval(() => {

        let playback_slider = document.querySelector(".playback_slider")
        let totalDuration = (duration.minuets * 60) + duration.seconds;
    
        if (totalDuration == 0) return;
        if (context == undefined) return;
        if (context.state == "closed") return;
        if (context.state == "suspended") return;
    
        time++;
        if (time >= totalDuration) {
            stop();
        }
    
        let elapsed = new Date(time * 1000).toISOString().slice(14, 19);
        timer.innerText = `${elapsed} / ${duration.minuets}:${duration.seconds}`;
        if ((time / totalDuration) * 100 <= 100) {
            progress.style.width = `${(time / totalDuration) * 100}%`
        }        
    }, ms);
}

startInterval(1000)