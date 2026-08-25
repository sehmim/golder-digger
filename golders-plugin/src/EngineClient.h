#pragma once
#include <juce_core/juce_core.h>

namespace goldigger
{
/** POST a JSON body to the engine on loopback and return the response body.

    Hand-rolled over a socket rather than juce::URL: the request never leaves
    loopback, and NSURLSession's transport-security policy belongs to whichever
    host DAW loaded us -- a plain socket cannot be vetoed by its Info.plist.

    Its own translation unit so it can be exercised against a running engine
    without loading a plugin: see the EngineClientCheck target.

    `error` is set (and the return value empty) on any failure.
*/
juce::String postJson(const juce::String& host, int port, const juce::String& path,
                      const juce::String& body, juce::String& error,
                      int timeoutMs = 30000);
} // namespace goldigger
