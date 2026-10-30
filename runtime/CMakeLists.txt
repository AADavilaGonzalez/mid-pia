cmake_minimum_required(VERSION 3.15)

project(mid LANGUAGES C)

file(GLOB_RECURSE MID_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*"
)

add_library(mid STATIC ${MID_SOURCES})
