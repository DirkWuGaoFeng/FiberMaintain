include_directories(${PROTO_BIN_DIR})
include_directories(${CMAKE_SOURCE_DIR}/src/fiber_maint_service)

add_executable(fiber_maint_service
    main.cpp
    fiber_maint_service_impl.cpp
    fiber_topology_resolver.cpp
    target_builders.cpp
    color_strategy.cpp
    perf_executor.cpp
    spanloss_calculator.cpp
    dependency_builder.cpp
    output_layer.cpp
    pull_callback.cpp
)

target_link_libraries(fiber_maint_service
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)
