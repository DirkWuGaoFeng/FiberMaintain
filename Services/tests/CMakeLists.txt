include_directories(${PROTO_BIN_DIR})
include_directories(${CMAKE_SOURCE_DIR}/src/fiber_maint_service)

add_executable(fiber_maintain_test test_main.cpp)

target_link_libraries(fiber_maintain_test
    proto
    common
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)

# v4.0 unit tests + integration tests
add_executable(fiber_maint_test
    test_fiber_maint.cpp
    ${CMAKE_SOURCE_DIR}/src/fiber_maint_service/fiber_topology_resolver.cpp
    ${CMAKE_SOURCE_DIR}/src/fiber_maint_service/target_builders.cpp
    ${CMAKE_SOURCE_DIR}/src/fiber_maint_service/color_strategy.cpp
    ${CMAKE_SOURCE_DIR}/src/fiber_maint_service/perf_executor.cpp
    ${CMAKE_SOURCE_DIR}/src/fiber_maint_service/spanloss_calculator.cpp
    ${CMAKE_SOURCE_DIR}/src/fiber_maint_service/dependency_builder.cpp
)

target_link_libraries(fiber_maint_test
    proto
    common
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)
