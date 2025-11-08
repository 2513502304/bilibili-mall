# **网页链接**
**会员购**: "https://mall.bilibili.com/"
- **手办**: "https://www.biligo.com/list.html?noTitleBar=1&from=category_sb&category=1_107&scene=figure#sortType=totalrank&sortOrder=false&isInStock=false&detailFilter="
    - **比例手办**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_142&scene=figure&from=category_blsb#sortType=totalrank&sortOrder=false&isInStock=false"
    - **景品**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_175&scene=figure&from=category_jingpin#sortType=totalrank&sortOrder=false&isInStock=false"
    - **雕像**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_829&scene=figure&from=category_dx#sortType=totalrank&sortOrder=false&isInStock=false"
    - **Q 版手办**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_121&scene=figure&from=category_qbsb#sortType=totalrank&sortOrder=false&isInStock=false"
    - **可动手办**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_122&scene=figure&from=category_kdsb#sortType=totalrank&sortOrder=false&isInStock=false"
    - **盒蛋**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_124&scene=figure&from=category_hd#sortType=totalrank&sortOrder=false&isInStock=false"
    - **一番赏**: "https://mall.bilibili.com/neul-next/index.html?page=category_list&noTitleBar=1&category=2_876&scene=model&from=category_yfs"
- **市集**: "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
    - **特定的商品页面链接（c2cItemsId = "177914243276"）**: "https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={c2cItemsId}&from=market_index"

# **API**
- **市集 API**: "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
    - **市集滑动刷新商品列表 API（post）**: "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
        - post 方法的请求负载：
            ```python
            {
                "sortType": "TIME_DESC",  # 排序类型，可选值：TIME_DESC（综合，默认时间降序）、PRICE_DESC（价格倒序）、PRICE_ASC（价格升序）
                "priceFilters": [ # 价格过滤类型
                    "0-2000",   # 20 以下
                    "2000-3000",   # 20 - 30
                    "3000-5000",   # 30 - 50
                    "5000-10000",  # 50 - 100
                    "10000-20000", # 100 - 200
                    "20000-0"     # 200 以上
                ],
                "discountFilters": [  # 折扣类型
                    "0-30", # 3 折以下
                    "30-50", # 3 - 5 折
                    "50-70", # 5 - 7 折
                    "70-100" # 7 折以上
                ],
                nextId": null    # 分页标识，第一次请求时传 null，后续请求时传上一次响应中的 nextId
            }
            ```
        - 返回响应内容：
            ```python
            {
                "success": true,
                "data": {
                    "data": [
                        {
                            "c2cItemsId": 177914243276,   # 商品 id
                            "type": 1,
                            "c2cItemsName": "TAITO 伊蕾娜 水着ver. 景品手办",   # 商品名称
                            "detailDtoList": [  # 商品中包含物品的详情列表
                                {
                                    "blindBoxId": 211257889,
                                    "itemsId": 11167710,    # 物品 id
                                    "skuId": 1004348723,    # sku id
                                    "name": "TAITO 伊蕾娜 水着ver. 景品手办",   # 物品名称
                                    "img": "//i0.hdslb.com/bfs/mall/mall/25/f0/25f098380d5a7dc7056b7ae8c1ee7fee.png",   # 物品图片链接
                                    "marketPrice": 11200,   # 物品原价（市场价）* 100
                                    "type": 0,
                                    "isHidden": false
                                }
                            ],
                            "totalItemsCount": 1,   # 物品个数，与 detailDtoList 的长度相同
                            "price": 10000, # 商品售价（出售价）* 100
                            "showPrice": "100", # 商品售价（出售价）
                            "showMarketPrice": "112",   # 商品原价（市场价）
                            "uid": "10***9",    # 用户 uid
                            "paymentTime": 0,
                            "isMyPublish": false,   # 是否为我发布的商品
                            "uname": "欧***",   # 卖家用户名称
                            "uface": "https://i1.hdslb.com/bfs/face/4601dbb75aa4ec80773435b45026fccbd6a9b5c4.jpg",  # 卖家用户头像链接
                            "uspaceJumpUrl": null
                        },
                        ...
                    ],
                    "nextId": "Lg7VRJlDxLtC2j4L60F0gEdJm4dEYHeeCf7WjhbgtFY="    # 分页标识
                },
                "header": null,
                "code": 0,
                "message": null
            }
            ```
    - **特定的商品详情页 API（get，c2cItemsId = "177914243276"）**: "https://mall.bilibili.com/mall-magic-c/internet/c2c/items/queryC2cItemsDetail?c2cItemsId={c2cItemsId}"
        - get 方法的查询字符串：
            ```python
            c2cItemsId = "177914243276" # 商品 id
            ```
        - 返回响应内容：
            ```python
            {
                "success": true,
                "data": {
                    "c2cItemsId": 177914243276, # 商品 id
                    "type": 1,
                    "c2cItemsName": "TAITO 伊蕾娜 水着ver. 景品手办",   # 商品名称
                    "detailDtoList": [  # 商品中包含物品的详情列表
                        {
                            "blindBoxId": 211257889,
                            "itemsId": 11167710,    # 物品 id
                            "skuId": 1004348723,    # sku id
                            "name": "TAITO 伊蕾娜 水着ver. 景品手办",   # 物品名称
                            "img": "//i0.hdslb.com/bfs/mall/mall/25/f0/25f098380d5a7dc7056b7ae8c1ee7fee.png",   # 物品图片链接
                            "marketPrice": 11200,   # 物品原价（市场价）* 100
                            "showMarketPrice": "112",   # 物品原价（市场价）
                            "forbidExchange": true,
                            "isDraw": true,
                            "style": 1,
                            "boxItemsId": 11339161,
                            "boxSkuId": 1005233479,
                            "type": 0,
                            "predictArriveTime": null,
                            "isHidden": false,
                            "cateName": ""
                        }
                    ],
                    "totalItemsCount": 1,   # 物品个数，与 detailDtoList 的长度相同
                    "price": 10000, # 商品售价（出售价）* 100
                    "showPrice": "100", # 商品售价（出售价）
                    "marketPrice": "112",   # 商品原价（市场价）
                    "remainSecond": 1295435,    # 商品剩余时间，单位为秒
                    "uid": "10***9",    # 用户 uid
                    "publishStatus": 1,
                    "dropReason": null,
                    "isMyPublish": false,   # 是否为我发布的商品
                    "isMyBuyer": false,  # 是否为我购买的商品
                    "saleStatus": 1,
                    "buyerUid": null,
                    "buyerName": null,
                    "buyerFace": null,
                    "saleTime": 0,
                    "buyerNotice": "<h2><strong>重要提示：</strong></h2><p>*您购买的商品将继承卖家的自动发货到期时间，您盒柜中原有的发货规则对于该商品仍然适用，请仔细确认商品信息。</p><p>*标题前含有“福袋”二字的商品，为福袋商品，其中包含未知盲盒款，具有不确定性，请仔细确认商品信息。</p><h2><strong>其他须知：</strong></h2><p>1.交易不改变商品（包括福袋商品）的进阶属性，原本可进阶的在交易后仍可进阶，进阶商品大礼包、合成商品等不支持进阶的则交易后也不支持进阶。</p><p>2.当您在盲盒集市购买商品时，请务必仔细确认所购商品的描述（包括但不限于名称、价格、数量、型号、规格、尺寸、发货时限、是否为现货等重要事项）。当您在盲盒集市购买福袋商品时，因福袋商品存在不确定性，请务必仔细确认所购商品的描述（包括但不限于名称、价格、数量、型号、规格、尺寸、发货时限、是否为现货等重要事项）。</p><p>3.划线价系参考价格，由于时间差异、市场波动，该价格存在变化或者差异，仅供参考。</p><p>4.请您确保你预留的联系地址、电话、收货人等信息都真实有效，在申请发货前进行核对，并且当收货信息发生变化时及时进行更新。因您地址错误或其他个人原因导致的任何损失由您自行承担。</p><p>5.请您下单后在规定时间内完成支付，超时未支付盲盒市集将自动取消订单。具体时间请在下单页面仔细确认。</p><p>6.请勿相信卖家私下交易信息的引导，私下交易将不受平台保护，所造成的一切损失将由用户自行承担。</p><p>7.请您关注购买商品的发货信息，如未在预计时间内收到商品，或商品存在错发/漏发，请您保留凭证及时向平台进行反馈。</p><p>8.市集为买卖双方进行的闲置物品交易的平台，交易商品概不支持退款。如商品存在质量问题，您可联系平台进行换货处理。</p>",
                    "startBuyTime": 1759338862, # 购买开始时间戳
                    "publishTime": 1759338682,  # 商品发布时间戳
                    "orderId": null,
                    "hiddenFudaiImg": "https://i0.hdslb.com/bfs/activity-plat/static/20230525/97c40e378c8720c763d566d91950756c/DX1ynBgMeB.png",
                    "uname": "欧***",   # 卖家用户名称
                    "uspaceJumpUrl": null,
                    "uface": "https://i1.hdslb.com/bfs/face/4601dbb75aa4ec80773435b45026fccbd6a9b5c4.jpg"   # 卖家用户头像链接
                },
                "header": null,
                "code": 0,
                "message": null
            }
            ```
    - **推荐盲盒 API（post）**: "https://mall.bilibili.com/magic-c-search/items/recommend/blindbox"
        - post 方法的请求负载：
            ```python
            {
                "itemsId": 11167710,  # 物品 id
                "bizType": 1
            }
            ```
        - 返回响应内容：
            ```python
            {
                "success": true,
                "data": [
                    {
                        "id": 13220075,
                        "title": "魔力赏推荐",
                        "name": "【社群专享】超神高概率！人气合集！",
                        "price": 12.0,
                        "itemsType": 3,
                        "tagNames": null,
                        "savePrice": 107.0,
                        "allSkuNum": 39,
                        "rareSkuNum": 34,
                        "jumpUrl": "https://mall.bilibili.com/neul-next/index.html?page=magic-detail_detail&activeType=1&noTitleBar=1&itemsId=13220075&recId=&from=draw-card",
                        "itemsImg": null,
                        "subSkuList": [
                            {
                                "imageUrl": "//i0.hdslb.com/bfs/mall/mall/25/f0/25f098380d5a7dc7056b7ae8c1ee7fee.png",
                                "type": 3,
                                "name": "TAITO 伊蕾娜 水着ver. 景品手办",
                                "subSkuId": 1004348723,
                                "subItemsId": 11167710,
                                "subSkuPrice": 119.0
                            },
                            ...
                        ],
                        "reportParams": null
                    },
                    ...
                ],
                "header": null,
                "code": 0,
                "message": null
            }
            ```