// Exercises the plugin's HTTP client against a running engine, without a host.
//
// It exists because the failure it guards is invisible in a build and in
// auval: a non-blocking read that treats "nothing has arrived yet" as
// end-of-stream compiles, validates, and then makes every DIG come back empty.
//
//   golddigger serve &
//   ./build/EngineClientCheck_artefacts/EngineClientCheck [wav ...]
//
// Exits non-zero with a message naming what failed.
#include <juce_core/juce_core.h>
#include "../src/EngineClient.h"

static int fail(const juce::String& why)
{
    std::cerr << "FAIL: " << why << std::endl;
    return 1;
}

int main(int argc, char* argv[])
{
    // No message loop: sockets and JSON are juce_core, and this deliberately
    // exercises the client with nothing else running.
    juce::String error;

    // /health first: it answers immediately, so a failure here is the client,
    // not the engine taking its time.
    const auto health = goldigger::postJson("127.0.0.1", 8420, "/health", "{}", error);
    if (error.isNotEmpty() && ! error.contains("405"))
        return fail("GET-shaped /health: " + error);

    juce::Array<juce::var> paths;
    for (int i = 1; i < argc; ++i)
        paths.add(juce::String(juce::CharPointer_UTF8(argv[i])));
    if (paths.isEmpty())
        return fail("pass at least one wav to use as the context");

    auto* req = new juce::DynamicObject();
    req->setProperty("context_paths", paths);
    req->setProperty("distance", 50.0);
    req->setProperty("k", 5);
    req->setProperty("bpm", 174.0);

    const auto body = goldigger::postJson("127.0.0.1", 8420, "/session/analyze",
                                          juce::JSON::toString(juce::var(req), true),
                                          error);
    if (error.isNotEmpty())
        return fail("/session/analyze: " + error);

    const auto parsed = juce::JSON::parse(body);
    auto* results = parsed["results"].getArray();
    if (results == nullptr)
        return fail("no results array in: " + body.substring(0, 200));

    std::cout << "anchor=" << parsed["novelty_anchor"].toString()
              << "  bpm=" << parsed["context"]["bpm"].toString()
              << "  results=" << results->size() << std::endl;
    for (const auto& r : *results)
        std::cout << "  " << juce::File(r["path"].toString()).getFileName()
                  << "  fit=" << r["fit"].toString()
                  << "  novelty=" << r["novelty"].toString() << std::endl;

    if (results->isEmpty())
        return fail("the engine returned an empty result set");
    if (std::abs((double) parsed["context"]["bpm"] - 174.0) > 0.001)
        return fail("the stated bpm did not reach the context: "
                    + parsed["context"]["bpm"].toString());
    if (parsed["novelty_anchor"].toString() != "context")
        return fail("a context with its own audio must not borrow an anchor");
    std::cout << "PASS" << std::endl;
    return 0;
}
