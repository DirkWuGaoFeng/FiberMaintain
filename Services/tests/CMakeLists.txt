include_directories(${PROTO_BIN_DIR})

add_executable(fiber_maintain_test test_main.cpp)

target_link_libraries(fiber_maintain_test
    proto
    common
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)

add_executable(fiber_maint_test test_fiber_maint.cpp)

target_link_libraries(fiber_maint_test
    proto
    common
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)