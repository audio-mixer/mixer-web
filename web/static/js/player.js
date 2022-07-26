const protocol = location.protocol == "http:" ? "ws" : "wss";
const ws = new WebSocket(`${protocol}://${location.host}/stream`);
ws.binaryType = "arraybuffer";

let context;
let time = 0;
let init = 0;
let nextTime = 0;
let audioStack = [];

// information about current track
let nchannels = 0;
let sampwidth = 0;
let framerate = 0;
let frames = 0;
let comptype = "";
let compname = "";
let duration = { hours: 0, minuets: 0, seconds: 0 };

try {
    window.AudioContext = window.AudioContext || window.webkitAudioContext;
} catch (e) {
    alert("Web Audio API is not supported in this browser");
}

// handle audio player btn interations
const timer = document.querySelector(".timer");
const track = document.querySelector(".track");
const player = document.querySelector(".player");
const stopbtn = document.querySelector(".stopbtn");
const playbackToggle = document.querySelector(".playback-tg");
stopbtn.addEventListener("click", (e) => {if (!e.target.classList.contains("gray")) stop();});
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
        return;
    }

    // resume playback
    if (context.state == "suspended") {
        context.resume();
        playbackToggle.classList.add("bi-pause-fill");
        playbackToggle.classList.remove("bi-play-fill");
        return;
    }
});

// handle the incomming audio data
ws.onmessage = (message) => {
    if (message.data instanceof ArrayBuffer) {
        context.decodeAudioData(message.data, (buffer) => {
        // console.log(buffer.duration)
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
        nchannels = data.nchannels;
        sampwidth = data.sampwidth;
        framerate = data.framerate;
        comptype = data.comptype;
        compname = data.compname;
        duration = data.duration;
        frames = data.frames;
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
    ws.send(JSON.stringify({
        source: source,
        commands: ["STREAM", "GET"],
    }));

    stopbtn.classList.remove("gray");
    playbackToggle.classList.add("bi-pause-fill");
    playbackToggle.classList.remove("gray", "bi-play-fill");
}

// begin playing audio from buffer
function playBuffer() {
    while (audioStack.length) {
        let buffer = audioStack.shift();
        let source = context.createBufferSource();
        source.buffer = buffer;
        source.connect(context.destination);
        if (nextTime == 0) {
        nextTime = context.currentTime + 0.05;
        }

        source.start(nextTime);
        nextTime += source.buffer.duration;
    }
}

// stops playback
function stop() {
    if (context == undefined || context.state == "closed") {
        return;
    }

    context.close()[init, nextTime] = [0, 0];
    ws.send(JSON.stringify({
        commands: ["STOP"],
    }));

    time = 0;
    track.setAttribute("max", 0);
    track.setAttribute("value", time);
    timer.innerText = `0:00 / 0:00`;
    stopbtn.classList.add("gray");
    playbackToggle.classList.add("bi-play-fill");
    playbackToggle.classList.remove("bi-pause-fill");
}

// custom listener
setInterval(() => {
    if (context == undefined) return;
    if (context.state == "closed") return;
    if (context.state == "suspended") return;

    time++;
    if (time >= (duration.minuets * 60) + duration.seconds) {
        stop();
    }

    track.stepUp(1);
    track.setAttribute("max", (duration.minuets * 60) + duration.seconds);
    let elapsed = new Date(time * 1000).toISOString().slice(14, 19);
    timer.innerText = `${elapsed} / ${duration.minuets}:${duration.seconds}`;
}, 1000);
