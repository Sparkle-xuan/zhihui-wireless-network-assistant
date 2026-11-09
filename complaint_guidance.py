"""Complaint wording draft. Placeholders require confirmation before use."""

SCENARIOS = {
    'first_contact': ('首次联系', '我是移动公司网络投诉处理人员，您反映的网络问题由我负责跟进。请问现在方便占用您一点时间，了解一下具体情况吗？'),
    'appointment': ('预约现场测试', '为了进一步了解您反映的问题，我们希望在您方便的时候进行现场测试。请问您什么时间方便？'),
    'non_network': ('已核实非网络问题', '关于您反映的使用问题，经核实与【已确认的终端、手机卡或其他情况】有关。我们可以协助您了解【已确认的处理方式】，如后续还有问题请与我们联系。'),
    'unable_to_test': ('暂无法现场测试', '关于您反映的网络问题，由于目前尚未能在具体地点完成测试，我们暂时无法准确判断原因。待您方便时，请与我们联系，我们会继续为您安排处理。'),
    'fault': ('已核实故障', '关于您反映的网络问题，经核实与【已确认的故障情况】有关，目前【已确认的处理进展】。给您带来的不便，我们深表歉意。'),
    'interference': ('已核实干扰', '关于您反映的网络问题，经核实与【已确认的干扰情况】有关，目前【已确认的处理进展】。给您带来的不便，我们深表歉意。'),
    'coordination': ('建设协调中', '针对您反映的问题，我们正在结合实际情况推进【已确认的协调事项】。如有新的进展，我们会及时向您说明，感谢您的理解。'),
    'long_term': ('短期无法解决', '我们已记录您反映的网络使用问题，正在结合实际情况研究改善方案。由于方案及实施周期尚需确认，暂不能向您承诺具体完成时间，有进展后会及时与您沟通。'),
    'resolved': ('处理后效果确认', '关于您反映的网络问题，我们已完成【已确认的处理措施】。想向您确认一下，目前使用情况是否有改善？如仍有问题，请随时与我们联系。'),
    'unreachable': ('联系未接通', '关于您反映的网络问题，我们曾尝试与您联系但未能接通。方便时您可以通过【已确认的本地联系电话】与我们联系，我们会继续为您跟进。'),
}


def guidance(scenario, global_customer=False):
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise ValueError('请选择有效的服务场景。')
    if type(global_customer) is not bool:
        raise ValueError('用户类型无效。')
    title, body = SCENARIOS[scenario]
    prefix = '尊敬的全球通用户，您好！' if global_customer else '您好！'
    return {'title': title, 'text': prefix + body,
            'note': '方括号内容需根据实际核实情况填写；未经确认不要承诺解决方案或时限。'}
