# The following lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.16)

# Add this line to disable the specific warning
add_compile_options(-Wno-missing-field-initializers)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
# "Trim" the build. Include the minimal set of components, main, and anything it depends on.
idf_build_set_property(MINIMAL_BUILD ON)

set(PROJECT_VER "2.2.6")
project(xiaozhi)

idf_component_get_property(network_library 78__esp-ml307 COMPONENT_LIB)
get_target_property(network_sources ${network_library} SOURCES)
list(FILTER network_sources EXCLUDE REGEX "src/esp/esp_(tcp|network)\\.cc$")
set_property(TARGET ${network_library} PROPERTY SOURCES "${network_sources}")
target_sources(${network_library} PRIVATE
    "${CMAKE_CURRENT_LIST_DIR}/main/network/esp_tcp.cc"
    "${CMAKE_CURRENT_LIST_DIR}/main/network/esp_network.cc")
