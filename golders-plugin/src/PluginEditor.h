#pragma once
#include <JuceHeader.h>
#include "PluginProcessor.h"

// One dial, one button, one list -- the same three ideas as the desktop app,
// with the one thing only a plugin can offer: a result row dragged out of the
// list is a file drop the host accepts like any other.
class GoldDiggerBridgeEditor : public juce::AudioProcessorEditor,
                               private juce::ListBoxModel
{
public:
    explicit GoldDiggerBridgeEditor(GoldDiggerBridgeProcessor&);

    void paint(juce::Graphics&) override;
    void resized() override;

private:
    int getNumRows() override;
    void paintListBoxItem(int, juce::Graphics&, int, int, bool) override {}
    juce::Component* refreshComponentForRow(int, bool, juce::Component*) override;

    void startDig();
    void finished(juce::var response, juce::String error);

    GoldDiggerBridgeProcessor& processor;
    juce::Slider distance;
    juce::AudioProcessorValueTreeState::SliderAttachment distanceAttachment;
    juce::Label surface, deep, status;
    juce::TextButton digButton { "DIG" };
    juce::ListBox list;
    juce::Array<juce::var> results;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(GoldDiggerBridgeEditor)
};
