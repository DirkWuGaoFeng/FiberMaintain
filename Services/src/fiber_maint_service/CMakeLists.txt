include_directories(${PROTO_BIN_DIR})

add_executable(fiber_maint_service
    main.cpp
    fiber_maint_service_impl.cpp
)

target_link_libraries(fiber_maint_service
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)