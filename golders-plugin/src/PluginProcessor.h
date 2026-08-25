#pragma once
#include <JuceHeader.h>

// The bridge, not the brain: audio passes through untouched while the last few
// seconds are kept in a ring; DIG writes that capture to a temp wav and asks
// the engine on localhost to rank the library against it, stating the host's
// transport tempo outright (AnalyzeReq.bpm). Every measurement stays in the
// Python engine -- this plugin's only jobs are to hear the session and to hand
// results back as files a DAW will accept by drag.
class GoldDiggerBridgeProcessor : public juce::AudioProcessor
{
public:
    GoldDiggerBridgeProcessor();

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "Gold Digger Bridge"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override { return {}; }
    void changeProgramName(int, const juce::String&) override {}

    void getStateInformation(juce::MemoryBlock&) override;
    void setStateInformation(const void*, int) override;

    // Captures on the calling thread, then asks the engine on a background
    // one; `done` lands on the message thread with the engine's parsed JSON,
    // or an error that names what went wrong. Call from the message thread.
    void dig(double distance, std::function<void(juce::var, juce::String)> done);

    double hostBpm() const { return currentBpm.load(); }

    juce::AudioProcessorValueTreeState state;

private:
    static constexpr double captureSeconds = 8.0;

    juce::AudioBuffer<float> capture;   // mono ring of the last captureSeconds
    std::atomic<int> writePos { 0 };
    std::atomic<bool> wrapped { false };
    std::atomic<double> currentBpm { 0.0 };
    double sr = 44100.0;

    // Guards the ring's *allocation* only -- prepareToPlay reallocates it while
    // a dig may be reading it. Never taken on the audio thread: processBlock
    // writes into whatever allocation is current, and a torn sample or two in
    // an eight-second analysis capture is not worth a lock on the audio path.
    juce::CriticalSection captureLock;

    // Owned, not detached: juce::Thread::launch leaves a running lambda that
    // nothing ever joins. The job itself captures no processor state (see
    // dig), because this pool's destructor only waits five seconds and a
    // stalled request outlasts that.
    juce::ThreadPool digPool { 1 };

    juce::File writeCapture(juce::String& error);

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(GoldDiggerBridgeProcessor)
};
