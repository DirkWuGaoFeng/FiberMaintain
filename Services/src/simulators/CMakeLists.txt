include_directories(${PROTO_BIN_DIR})

add_executable(scene_simulator scene_simulator.cpp)
target_link_libraries(scene_simulator
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    Threads::Threads
)

add_executable(alarm_simulator alarm_simulator.cpp)
target_link_libraries(alarm_simulator
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    Threads::Threads
)

add_executable(performance_simulator performance_simulator.cpp)
target_link_libraries(performance_simulator
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    Threads::Threads
)