#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "EngineClient.h"

GoldDiggerBridgeProcessor::GoldDiggerBridgeProcessor()
    : AudioProcessor(BusesProperties()
                         .withInput("Input", juce::AudioChannelSet::stereo(), true)
                         .withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      state(*this, nullptr, "params",
            { std::make_unique<juce::AudioParameterFloat>("distance", "Distance",
                                                          0.0f, 100.0f, 50.0f) })
{
}

void GoldDiggerBridgeProcessor::prepareToPlay(double sampleRate, int)
{
    const juce::ScopedLock sl(captureLock);     // a dig may be reading the old one
    sr = sampleRate;
    capture.setSize(1, (int) (sampleRate * captureSeconds));
    capture.clear();
    writePos.store(0);
    wrapped.store(false);
}

bool GoldDiggerBridgeProcessor::isBusesLayoutSupported(const BusesLayout& layouts) const
{
    // mono or stereo, but never a channel count change across the insert
    const auto& in = layouts.getMainInputChannelSet();
    return in == layouts.getMainOutputChannelSet()
        && (in == juce::AudioChannelSet::mono() || in == juce::AudioChannelSet::stereo());
}

void GoldDiggerBridgeProcessor::processBlock(juce::AudioBuffer<float>& buffer,
                                             juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;

    if (auto* playhead = getPlayHead())
        if (auto pos = playhead->getPosition())
            if (auto bpm = pos->getBpm())
                currentBpm.store(*bpm);

    const int n = buffer.getNumSamples();
    const int chans = buffer.getNumChannels();
    const int cap = capture.getNumSamples();
    if (cap > 0 && n > 0 && chans > 0)
    {
        int w = writePos.load();
        auto* dst = capture.getWritePointer(0);
        for (int i = 0; i < n; ++i)
        {
            float mono = 0.0f;
            for (int c = 0; c < chans; ++c)
                mono += buffer.getReadPointer(c)[i];
            dst[w] = mono / (float) chans;
            if (++w == cap) { w = 0; wrapped.store(true); }
        }
        writePos.store(w);
    }
    // the audio itself passes through untouched
}

juce::File GoldDiggerBridgeProcessor::writeCapture(juce::String& error)
{
    juce::AudioBuffer<float> snap;
    double rate = 0.0;
    {
        // held only for the copy: prepareToPlay must not free the ring
        // out from under it
        const juce::ScopedLock sl(captureLock);
        const int cap = capture.getNumSamples();
        const int w = juce::jmin(writePos.load(), cap);
        const bool full = wrapped.load();
        const int total = full ? cap : w;
        rate = sr;
        if (total < (int) (rate * 0.25))
        {
            error = "nothing captured yet -- play audio through the plugin first";
            return {};
        }
        // reader-side copy while the audio thread keeps writing: a torn sample
        // or two in an eight-second analysis capture is not worth a lock on
        // the audio path
        snap.setSize(1, total);
        if (full)
        {
            snap.copyFrom(0, 0, capture, 0, w, cap - w);
            snap.copyFrom(0, cap - w, capture, 0, 0, w);
        }
        else
            snap.copyFrom(0, 0, capture, 0, 0, w);
    }

    auto tmp = juce::File::getSpecialLocation(juce::File::tempDirectory)
                   .getNonexistentChildFile("golddigger-capture", ".wav");
    auto stream = std::make_unique<juce::FileOutputStream>(tmp);
    if (! stream->openedOk())
    {
        error = "could not write " + tmp.getFullPathName();
        return {};
    }
    juce::WavAudioFormat wav;
    std::unique_ptr<juce::AudioFormatWriter> writer(
        wav.createWriterFor(stream.get(), rate, 1, 16, {}, 0));
    if (writer == nullptr)
    {
        error = "could not create a wav writer";
        return {};
    }
    stream.release();   // the writer owns the stream now
    writer->writeFromAudioSampleBuffer(snap, 0, snap.getNumSamples());
    return tmp;
}

void GoldDiggerBridgeProcessor::dig(double distance,
                                    std::function<void(juce::var, juce::String)> done)
{
    // The capture is taken here, on the calling thread, so that everything the
    // background job needs is a value it owns. Nothing below captures `this`:
    // a host may delete the plugin while the engine is still thinking, and a
    // job still holding the processor would be a use-after-free. The pool is a
    // member so its destructor also waits -- but only for five seconds, which
    // is shorter than a stalled request, so not touching `this` is what
    // actually makes this safe.
    juce::String error;
    const auto wav = writeCapture(error);
    if (error.isNotEmpty())
    {
        done({}, error);
        return;
    }
    const double bpm = currentBpm.load();

    digPool.addJob([wav, distance, bpm, done]
    {
        juce::String jobError;
        juce::var parsed;
        auto* req = new juce::DynamicObject();
        juce::Array<juce::var> paths;
        paths.add(wav.getFullPathName());
        req->setProperty("context_paths", paths);
        req->setProperty("distance", distance);
        req->setProperty("k", 12);
        if (bpm > 0)
            req->setProperty("bpm", bpm);
        const auto response = goldigger::postJson(
            "127.0.0.1", 8420, "/session/analyze",
            juce::JSON::toString(juce::var(req), true), jobError);
        if (jobError.isEmpty())
            parsed = juce::JSON::parse(response);
        wav.deleteFile();       // the engine has read it by now
        juce::MessageManager::callAsync([done, parsed, jobError]
                                        { done(parsed, jobError); });
    });
}

void GoldDiggerBridgeProcessor::getStateInformation(juce::MemoryBlock& dest)
{
    if (auto xml = state.copyState().createXml())
        copyXmlToBinary(*xml, dest);
}

void GoldDiggerBridgeProcessor::setStateInformation(const void* data, int size)
{
    if (auto xml = getXmlFromBinary(data, size))
        state.replaceState(juce::ValueTree::fromXml(*xml));
}

juce::AudioProcessorEditor* GoldDiggerBridgeProcessor::createEditor()
{
    return new GoldDiggerBridgeEditor(*this);
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new GoldDiggerBridgeProcessor();
}
