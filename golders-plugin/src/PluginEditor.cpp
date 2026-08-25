#include "PluginEditor.h"

namespace
{
// the desktop theme's tokens, dark variant: chrome stays dust, gold is
// reserved for what was found
const juce::Colour BG(0xff23241f), SURFACE(0xff2c2d27), TEXT(0xffeceee8),
    MUTED(0xff9a9d92), GOLD(0xffc9a227);

// A row is a component (not painted by the model) so it can start an external
// drag: a file dropped on the host's timeline is the entire point.
class ResultRow : public juce::Component
{
public:
    void set(const juce::var& result)
    {
        path = result["path"].toString();
        auto meta = juce::StringArray();
        if (result["role"].toString().isNotEmpty())
            meta.add(result["role"].toString());
        if (! result["bpm"].isVoid())
            meta.add(result["bpm"].toString() + " BPM");
        if (result["tonic"].toString().isNotEmpty())
            meta.add(result["tonic"].toString());
        line = juce::File(path).getFileName();
        detail = meta.joinIntoString(" / ");
        repaint();
    }

    void paint(juce::Graphics& g) override
    {
        g.setColour(SURFACE);
        g.fillRoundedRectangle(getLocalBounds().toFloat().reduced(2.0f, 1.0f), 4.0f);
        g.setColour(TEXT);
        g.setFont(juce::FontOptions(13.0f, juce::Font::bold));
        g.drawText(line, 10, 2, getWidth() - 20, getHeight() / 2 + 2,
                   juce::Justification::bottomLeft);
        g.setColour(MUTED);
        g.setFont(juce::FontOptions(11.0f));
        g.drawText(detail, 10, getHeight() / 2 + 2, getWidth() - 20,
                   getHeight() / 2 - 4, juce::Justification::topLeft);
    }

    void mouseDrag(const juce::MouseEvent& e) override
    {
        if (dragging || path.isEmpty() || e.getDistanceFromDragStart() < 8)
            return;
        dragging = true;
        // The drag is asynchronous and the ListBox recycles rows: by the time
        // the drop finishes, this row may have been deleted or be showing a
        // different result. A SafePointer makes that a no-op instead of a
        // write into freed memory.
        juce::Component::SafePointer<ResultRow> safe(this);
        juce::DragAndDropContainer::performExternalDragDropOfFiles(
            { path }, false, this, [safe]() mutable
            {
                if (safe != nullptr)
                    safe->dragging = false;
            });
    }

private:
    juce::String path, line, detail;
    bool dragging = false;
};
} // namespace

GoldDiggerBridgeEditor::GoldDiggerBridgeEditor(GoldDiggerBridgeProcessor& p)
    : AudioProcessorEditor(&p), processor(p),
      distanceAttachment(p.state, "distance", distance)
{
    distance.setSliderStyle(juce::Slider::LinearHorizontal);
    distance.setTextBoxStyle(juce::Slider::TextBoxRight, false, 44, 20);
    distance.setColour(juce::Slider::trackColourId, GOLD.withAlpha(0.6f));
    distance.setColour(juce::Slider::thumbColourId, GOLD);
    addAndMakeVisible(distance);

    for (auto* label : { &surface, &deep })
    {
        label->setColour(juce::Label::textColourId, MUTED);
        label->setFont(juce::FontOptions(10.0f));
        addAndMakeVisible(*label);
    }
    surface.setText("SURFACE", juce::dontSendNotification);
    deep.setText("DEEP", juce::dontSendNotification);
    deep.setJustificationType(juce::Justification::centredRight);

    digButton.setColour(juce::TextButton::buttonColourId, GOLD);
    digButton.setColour(juce::TextButton::textColourOffId, BG);
    digButton.onClick = [this] { startDig(); };
    addAndMakeVisible(digButton);

    status.setColour(juce::Label::textColourId, MUTED);
    status.setFont(juce::FontOptions(11.0f));
    status.setText("insert on a bus, play, then dig", juce::dontSendNotification);
    addAndMakeVisible(status);

    list.setModel(this);
    list.setRowHeight(40);
    list.setColour(juce::ListBox::backgroundColourId, BG);
    addAndMakeVisible(list);

    setSize(420, 520);
}

void GoldDiggerBridgeEditor::paint(juce::Graphics& g)
{
    g.fillAll(BG);
    g.setColour(TEXT);
    g.setFont(juce::FontOptions(16.0f, juce::Font::bold));
    g.drawText("GOLD DIGGER", 16, 10, getWidth() - 32, 22, juce::Justification::left);
    g.setColour(MUTED);
    g.setFont(juce::FontOptions(10.0f));
    g.drawText("DIGGING FOR THE RIGHT SOUND", 16, 30, getWidth() - 32, 14,
               juce::Justification::left);
}

void GoldDiggerBridgeEditor::resized()
{
    auto area = getLocalBounds().reduced(16);
    area.removeFromTop(40);
    auto labels = area.removeFromTop(14);
    surface.setBounds(labels.removeFromLeft(80));
    deep.setBounds(labels.removeFromRight(80));
    distance.setBounds(area.removeFromTop(28));
    area.removeFromTop(8);
    digButton.setBounds(area.removeFromTop(34));
    area.removeFromTop(6);
    status.setBounds(area.removeFromTop(18));
    area.removeFromTop(6);
    list.setBounds(area);
}

void GoldDiggerBridgeEditor::startDig()
{
    digButton.setEnabled(false);
    const auto bpm = processor.hostBpm();
    status.setText(bpm > 0 ? "digging at " + juce::String(bpm, 1) + " BPM…"
                           : "digging…", juce::dontSendNotification);
    processor.dig(distance.getValue(),
                  [safe = juce::Component::SafePointer<GoldDiggerBridgeEditor>(this)]
                  (juce::var response, juce::String error)
                  {
                      if (safe != nullptr)
                          safe->finished(response, error);
                  });
}

void GoldDiggerBridgeEditor::finished(juce::var response, juce::String error)
{
    digButton.setEnabled(true);
    if (error.isNotEmpty())
    {
        status.setText(error, juce::dontSendNotification);
        return;
    }
    results.clear();
    if (auto* found = response["results"].getArray())
        results = *found;
    status.setText(juce::String(results.size()) + " finds -- drag one into your session",
                   juce::dontSendNotification);
    list.updateContent();
    list.repaint();
}

int GoldDiggerBridgeEditor::getNumRows() { return results.size(); }

juce::Component* GoldDiggerBridgeEditor::refreshComponentForRow(
    int row, bool, juce::Component* existing)
{
    if (row >= results.size())
    {
        delete existing;
        return nullptr;
    }
    auto* comp = dynamic_cast<ResultRow*>(existing);
    if (comp == nullptr)
    {
        delete existing;
        comp = new ResultRow();
    }
    comp->set(results.getReference(row));
    return comp;
}
