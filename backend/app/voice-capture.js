class VoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(800);
    this.offset = 0;
    this.done = false;
    this.port.onmessage = () => {
      this.done = true;
      if (this.offset) this.port.postMessage(this.buf.slice(0,this.offset).buffer);
      this.port.postMessage("finish");
    };
  }
  process(inputs) {
    if (this.done) return false;
    for (const x of inputs[0]?.[0] || []) {
      this.buf[this.offset++] = Math.round(Math.max(-1,Math.min(1,x)) * (x < 0 ? 32768 : 32767));
      if (this.offset === this.buf.length) {
        this.port.postMessage(this.buf.buffer,[this.buf.buffer]);
        this.buf = new Int16Array(800);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor("voice-capture",VoiceCapture);
