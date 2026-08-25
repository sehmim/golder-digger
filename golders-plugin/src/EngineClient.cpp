#include "EngineClient.h"

namespace goldigger
{
juce::String postJson(const juce::String& host, int port, const juce::String& path,
                      const juce::String& body, juce::String& error, int timeoutMs)
{
    error.clear();      // an out-param that only ever gets set reports the
                        // previous call's failure after this one succeeded
    juce::StreamingSocket socket;
    if (! socket.connect(host, port, 3000))
    {
        error = "engine not reachable on " + host + ":" + juce::String(port)
              + " -- start the Gold Digger app (or `golddigger serve`)";
        return {};
    }

    // Held in a local: toRawUTF8() points into the String's own storage, and a
    // temporary would be dead before the socket saw it.
    const juce::String head =
        "POST " + path + " HTTP/1.1\r\n"
        "Host: " + host + "\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: " + juce::String(body.getNumBytesAsUTF8()) + "\r\n"
        "Connection: close\r\n\r\n";
    const auto request = head + body;
    const auto* bytes = request.toRawUTF8();
    int remaining = (int) request.getNumBytesAsUTF8();
    while (remaining > 0)
    {
        const int n = socket.write(bytes, remaining);
        if (n <= 0)
        {
            error = "the engine hung up mid-request";
            return {};
        }
        bytes += n;
        remaining -= n;
    }

    // waitUntilReady before every read: a non-blocking read returns -1 for
    // "nothing has arrived yet", which is indistinguishable from a closed
    // socket at the call site -- reading straight into the loop below would
    // treat the engine's first seconds of thinking as end-of-stream and every
    // dig would come back empty.
    juce::MemoryOutputStream received;
    char chunk[8192];
    for (;;)
    {
        const int ready = socket.waitUntilReady(true, timeoutMs);
        if (ready < 0)
        {
            error = "the connection to the engine failed";
            return {};
        }
        if (ready == 0)
        {
            error = "the engine did not answer within "
                  + juce::String(timeoutMs / 1000) + "s";
            return {};
        }
        const int n = socket.read(chunk, sizeof(chunk), false);
        if (n <= 0)
            break;                      // the engine closed the connection: done
        received.write(chunk, (size_t) n);
    }

    const auto text = received.toString();
    const int headerEnd = text.indexOf("\r\n\r\n");
    if (headerEnd < 0)
    {
        error = "malformed response from the engine";
        return {};
    }
    const auto status = text.upToFirstOccurrenceOf("\r\n", false, false);
    const auto responseBody = text.substring(headerEnd + 4);
    if (! status.contains(" 200"))
    {
        error = status.fromFirstOccurrenceOf("HTTP/1.1 ", false, false)
              + ": " + responseBody.substring(0, 300);
        return {};
    }
    return responseBody;
}
} // namespace goldigger
