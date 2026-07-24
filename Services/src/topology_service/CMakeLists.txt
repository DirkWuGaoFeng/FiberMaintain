include_directories(${PROTO_BIN_DIR})

add_executable(topology_service
    main.cpp
    topology_service_impl.cpp
)

target_link_libraries(topology_service
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)