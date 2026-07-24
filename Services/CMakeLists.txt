cmake_minimum_required(VERSION 3.16)
project(FiberMaintain)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_SOURCE_DIR}/cmake")

find_package(Protobuf REQUIRED)
find_package(Threads REQUIRED)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GRPC REQUIRED grpc++)
pkg_check_modules(MYSQL REQUIRED mysqlclient)

include_directories(
    ${CMAKE_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/src
    ${PROTOBUF_INCLUDE_DIRS}
    ${GRPC_INCLUDE_DIRS}
    ${MYSQL_INCLUDE_DIRS}
)

set(PROTO_FILES
    common.proto
    board.proto
    topology.proto
    performance.proto
    alarm.proto
    fiber_maint.proto
)

set(PROTO_SRC_DIR ${CMAKE_SOURCE_DIR}/src/proto)
set(PROTO_BIN_DIR ${CMAKE_BINARY_DIR}/proto)
file(MAKE_DIRECTORY ${PROTO_BIN_DIR})

set(PROTO_SRCS "")
set(PROTO_HDRS "")

foreach(proto_file ${PROTO_FILES})
    get_filename_component(proto_name ${proto_file} NAME_WE)
    
    set(proto_src "${PROTO_BIN_DIR}/${proto_name}.pb.cc")
    set(proto_hdr "${PROTO_BIN_DIR}/${proto_name}.pb.h")
    set(grpc_src "${PROTO_BIN_DIR}/${proto_name}.grpc.pb.cc")
    set(grpc_hdr "${PROTO_BIN_DIR}/${proto_name}.grpc.pb.h")
    
    set(abs_proto_file "${PROTO_SRC_DIR}/${proto_file}")
    
    add_custom_command(
        OUTPUT ${proto_src} ${proto_hdr} ${grpc_src} ${grpc_hdr}
        COMMAND ${PROTOBUF_PROTOC_EXECUTABLE}
        ARGS --proto_path=${PROTO_SRC_DIR}
             --cpp_out=${PROTO_BIN_DIR}
             --grpc_out=${PROTO_BIN_DIR}
             --plugin=protoc-gen-grpc=/usr/bin/grpc_cpp_plugin
             ${proto_file}
        DEPENDS ${abs_proto_file}
        WORKING_DIRECTORY ${PROTO_SRC_DIR}
        COMMENT "Generating gRPC code for ${proto_file}"
    )
    
    list(APPEND PROTO_SRCS ${proto_src} ${grpc_src})
    list(APPEND PROTO_HDRS ${proto_hdr} ${grpc_hdr})
    
    include_directories(${PROTO_BIN_DIR})
endforeach()

add_library(proto STATIC ${PROTO_SRCS})
target_link_libraries(proto ${PROTOBUF_LIBRARIES} ${GRPC_LIBRARIES})

add_subdirectory(src/common)
add_subdirectory(src/board_service)
add_subdirectory(src/topology_service)
add_subdirectory(src/performance_service)
add_subdirectory(src/alarm_service)
add_subdirectory(src/fiber_maint_service)
add_subdirectory(src/api_gateway)
add_subdirectory(src/simulators)
add_subdirectory(tests)