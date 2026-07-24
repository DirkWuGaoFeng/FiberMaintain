include_directories(${PROTO_BIN_DIR})

add_executable(board_service
    main.cpp
    board_service_impl.cpp
)

target_link_libraries(board_service
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)