# The bridge plugin: AU + VST3. It contains no analysis -- it captures what the
# host plays, states the transport tempo, and asks the engine on localhost.
cmake_minimum_required(VERSION 3.22)
project(GoldDiggerBridge VERSION 0.1.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "")

include(FetchContent)
FetchContent_Declare(JUCE
  GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
  GIT_TAG 8.0.15
  GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(JUCE)

juce_add_plugin(GoldDiggerBridge
  COMPANY_NAME "Gold Digger"
  PRODUCT_NAME "Gold Digger Bridge"
  PLUGIN_MANUFACTURER_CODE Gldg
  PLUGIN_CODE Gdig
  FORMATS AU VST3
  COPY_PLUGIN_AFTER_BUILD TRUE
  NEEDS_WEB_BROWSER FALSE
  NEEDS_CURL FALSE)

target_sources(GoldDiggerBridge PRIVATE
  src/PluginProcessor.cpp
  src/PluginEditor.cpp
  src/EngineClient.cpp)

juce_generate_juce_header(GoldDiggerBridge)

target_compile_definitions(GoldDiggerBridge PRIVATE
  JUCE_WEB_BROWSER=0
  JUCE_USE_CURL=0
  JUCE_VST3_CAN_REPLACE_VST2=0)

target_link_libraries(GoldDiggerBridge
  PRIVATE juce::juce_audio_utils
  PUBLIC juce::juce_recommended_config_flags
         juce::juce_recommended_warning_flags)

# Exercises the engine client against a running engine, with no host and no
# plugin. The bug it guards -- a non-blocking read that reads "nothing yet" as
# end-of-stream -- compiles clean and passes auval, then makes every DIG return
# nothing. See tests/engine_client_check.cpp.
juce_add_console_app(EngineClientCheck PRODUCT_NAME "EngineClientCheck")
target_sources(EngineClientCheck PRIVATE
  tests/engine_client_check.cpp
  src/EngineClient.cpp)
target_compile_definitions(EngineClientCheck PRIVATE
  JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0
  JUCE_STANDALONE_APPLICATION=1)
target_link_libraries(EngineClientCheck
  PRIVATE juce::juce_core
  PUBLIC juce::juce_recommended_config_flags)
